"""Ember's CHIRP helper. Runs in its own virtualenv that has CHIRP installed.

It only reads and writes image FILES; it never opens a serial port (the radio
host's chirpc does that). Output is one JSON object on stdout.

  python radio_helper.py list  <chirp_id> <image>
  python radio_helper.py edit  <chirp_id> <image> <out_image>   (edits as JSON on stdin)
  python radio_helper.py info  <chirp_id> <image>

Edit format: {"edits": [{"number": 5, "name": "W0ABC", "freq": "146.940000",
  "duplex": "-", "offset": "0.600000", "tmode": "Tone", "rtone": 88.5,
  "ctone": 88.5, "dtcs": 23, "mode": "FM", "power": "High", "skip": ""},
  {"number": 6, "empty": true}]}
"""

from __future__ import annotations

import builtins
import json
import os
import sys
from pathlib import Path
from typing import Any

MAX_EDITS = 200
MAX_IMAGE_BYTES = 2 * 1024 * 1024
TEXT_FIELDS = ("name", "duplex", "tmode", "mode", "skip", "dtcs_polarity", "comment")


def _fail(message: str) -> None:
    print(json.dumps({"error": message[:300]}))
    sys.exit(1)


def _load(chirp_id: str, image: str) -> Any:
    from chirp import directory  # noqa: PLC0415

    directory.import_drivers()
    path = Path(image)
    if not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
        _fail("image file missing or too large")
    try:
        rclass = directory.get_radio(chirp_id)
    except Exception:  # noqa: BLE001
        _fail(f"unknown CHIRP model {chirp_id}")
    return rclass(str(path))


def _mem_dict(mem: Any) -> dict[str, Any]:
    return {
        "number": mem.number,
        "name": str(mem.name).rstrip(),
        "freq": mem.freq / 1e6,
        "duplex": mem.duplex,
        "offset": mem.offset / 1e6,
        "tmode": mem.tmode,
        "rtone": mem.rtone,
        "ctone": mem.ctone,
        "dtcs": mem.dtcs,
        "mode": mem.mode,
        "power": str(mem.power or ""),
        "skip": mem.skip,
    }


def _channels(radio: Any) -> list[dict[str, Any]]:
    start, end = radio.get_features().memory_bounds
    out = []
    for num in range(start, min(end, start + 2000) + 1):
        mem = radio.get_memory(num)
        if not mem.empty:
            out.append(_mem_dict(mem))
    return out


def _apply(radio: Any, edit: dict[str, Any]) -> None:
    from chirp import chirp_common  # noqa: PLC0415

    num = int(edit["number"])
    mem = radio.get_memory(num)
    if edit.get("empty"):
        mem.empty = True
        radio.set_memory(mem)
        return
    if mem.empty:
        mem = chirp_common.Memory()
        mem.number = num
    if "freq" in edit:
        mem.freq = chirp_common.parse_freq(str(edit["freq"]))
    if "offset" in edit:
        mem.offset = chirp_common.parse_freq(str(edit["offset"]))
    for key in TEXT_FIELDS:
        if key in edit:
            setattr(mem, key, str(edit[key]))
    for key in ("rtone", "ctone"):
        if key in edit:
            setattr(mem, key, float(edit[key]))
    if "dtcs" in edit:
        mem.dtcs = int(edit["dtcs"])
    if "power" in edit:
        levels = radio.get_features().valid_power_levels or []
        match = [p for p in levels if str(p).lower() == str(edit["power"]).lower()]
        if not match:
            raise ValueError(f"channel {num}: power must be one of {[str(p) for p in levels]}")
        mem.power = match[0]
    problems = radio.validate_memory(mem)
    if problems:
        raise ValueError(f"channel {num}: {'; '.join(str(p) for p in problems)[:200]}")
    radio.set_memory(mem)


def main(argv: list[str]) -> None:
    os.environ.setdefault("CHIRP_TESTENV", "1")
    if not hasattr(builtins, "_"):
        builtins._ = lambda text: text  # type: ignore[attr-defined]  # CHIRP's messages expect gettext
    if len(argv) < 3:
        _fail("usage: list|edit|info <chirp_id> <image> [out]")
    cmd, chirp_id, image = argv[0], argv[1], argv[2]
    radio = _load(chirp_id, image)
    if cmd == "list":
        print(json.dumps({"channels": _channels(radio)}))
    elif cmd == "info":
        rf = radio.get_features()
        print(
            json.dumps(
                {
                    "model": f"{radio.VENDOR} {radio.MODEL}",
                    "bounds": list(rf.memory_bounds),
                    "modes": list(rf.valid_modes),
                    "power": [str(p) for p in rf.valid_power_levels or []],
                }
            )
        )
    elif cmd == "edit" and len(argv) == 4:
        edits = json.loads(sys.stdin.read(200_000) or "{}").get("edits") or []
        if not isinstance(edits, list) or len(edits) > MAX_EDITS:
            _fail(f"edits must be a list of at most {MAX_EDITS}")
        try:
            for edit in edits:
                _apply(radio, edit)
        except Exception as exc:  # noqa: BLE001  # driver errors vary; report, never write a half-edited image
            _fail(f"{type(exc).__name__}: {exc}")
        radio.save_mmap(argv[3])
        print(json.dumps({"channels": _channels(radio)}))
    else:
        _fail("unknown command")


if __name__ == "__main__":
    main(sys.argv[1:])
