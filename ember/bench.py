"""Model speed sample: tokens/sec, time to first token and VRAM for the chat models.

Run on the P1 (`python -m ember.bench`) or from Users & admin -> Models -> Re-run.
Results go to data_dir/model-bench.json. The numbers are a sample from one run on
one machine; real speed depends on prompt length, what else is loaded and heat.
Stdlib only, loopback Ollama only.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess  # nosec B404 - fixed nvidia-smi argument list
import time
import urllib.request
from pathlib import Path
from typing import Any

MODELS = ("qwen3.5-9b-4k", "qwen3.5-9b-8k")
SAMPLE = Path(__file__).resolve().parent / "model_bench_sample.json"
FILENAME = "model-bench.json"
TIMEOUT_SEC = 900
OUT_TOKENS = 200
PARA = (
    "The Heltec WiFi LoRa 32 board pairs an ESP32-S3 with an SX1262 radio. The firmware reads sensors, "
    "packs a short message, sends it over LoRa and sleeps. Keep the loop bounded and check every return value. "
)
SHORT_WORDS = 60
FILL = 0.8  # the "full" run fills about 80% of the model's window
TOKENS_PER_WORD = 1.33


def _post(base: str, path: str, body: dict[str, Any], stream: bool = False) -> Any:
    if not base.startswith("http://127.0.0.1") and not base.startswith("http://localhost"):
        raise ValueError("Ollama must be on loopback")
    req = urllib.request.Request(  # noqa: S310 - loopback http only (checked above)
        base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    resp = urllib.request.urlopen(req, timeout=TIMEOUT_SEC)  # noqa: S310  # nosec B310
    if stream:
        return resp
    with resp:
        return json.loads(resp.read().decode())


def _get(base: str, path: str) -> Any:
    req = urllib.request.Request(base + path)  # noqa: S310
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310  # nosec B310
        return json.loads(resp.read().decode())


def ctx_tokens(model: str) -> int:
    m = re.search(r"-(\d{1,2})k$", model)
    return int(m.group(1)) * 1024 if m else 4096


def gpu() -> dict[str, Any]:
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return {"name": "", "total_mb": 0, "used_mb": 0}
    try:
        out = (
            subprocess.run(  # noqa: S603 # nosec B603
                [exe, "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            .stdout.strip()
            .splitlines()[0]
        )
        name, total, used = [p.strip() for p in out.split(",")[:3]]
        return {"name": name, "total_mb": int(total), "used_mb": int(used)}
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return {"name": "", "total_mb": 0, "used_mb": 0}


def unload_all(base: str) -> None:
    for m in _get(base, "/api/ps").get("models", [])[:10]:
        _post(base, "/api/generate", {"model": m["name"], "keep_alive": 0})
    time.sleep(3)


def one_run(base: str, model: str, words: int) -> dict[str, Any]:
    prompt = (PARA * max(1, words // 40))[: words * 5] + "\n\nSummarize the text above in one long paragraph."
    body = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "think": False,
        "keep_alive": "5m",
        "options": {"num_predict": OUT_TOKENS, "temperature": 0},
    }
    start = time.monotonic()
    first = 0.0
    final: dict[str, Any] = {}
    with _post(base, "/api/generate", body, stream=True) as resp:
        for count, line in enumerate(resp):
            if count > 20_000:
                break
            item = json.loads(line)
            if not first and item.get("response"):
                first = time.monotonic() - start
            if item.get("done"):
                final = item
                break
    ev, ed = int(final.get("eval_count") or 0), int(final.get("eval_duration") or 1)
    pc, pd = int(final.get("prompt_eval_count") or 0), int(final.get("prompt_eval_duration") or 1)
    return {
        "prompt_tokens": pc,
        "ttft_s": round(first, 1),
        "gen_tok_s": round(ev / (ed / 1e9), 1),
        "prompt_tok_s": round(pc / (pd / 1e9), 1),
        "total_s": round(time.monotonic() - start, 1),
    }


def bench_model(base: str, model: str) -> dict[str, Any]:
    unload_all(base)
    before = gpu()["used_mb"]
    cold = one_run(base, model, SHORT_WORDS)  # includes model load
    ps: dict[str, Any] = next((m for m in _get(base, "/api/ps").get("models", []) if m["name"].startswith(model)), {})
    after = gpu()["used_mb"]
    full = one_run(base, model, int(ctx_tokens(model) * FILL / TOKENS_PER_WORD))
    size, vram = int(ps.get("size") or 0), int(ps.get("size_vram") or 0)
    return {
        "model": model,
        "cold_start_s": cold["ttft_s"],
        "short": cold,
        "full": full,
        "ctx": ctx_tokens(model),
        "vram_mb": round(vram / 2**20),
        "model_mb": round(size / 2**20),
        "gpu_share": round(vram / size * 100) if size else 0,
        "gpu_used_delta_mb": max(0, after - before),
    }


def run(base: str = "http://127.0.0.1:11434", models: tuple[str, ...] = MODELS) -> dict[str, Any]:
    g = gpu()
    results = []
    for model in models:
        try:
            results.append(bench_model(base, model))
        except (OSError, ValueError, KeyError) as exc:
            results.append({"model": model, "error": str(exc)[:200]})
    unload_all(base)
    return {
        "date": time.strftime("%Y-%m-%d"),
        "host": platform.node(),
        "hardware": f"{g['name'] or 'unknown GPU'} {round(g['total_mb'] / 1024)} GB" if g["total_mb"] else "CPU",
        "note": "Sample from one run on this machine; actual speed varies with prompt length and load.",
        "results": results,
    }


def load(data_dir: Path) -> dict[str, Any]:
    for src in (data_dir / FILENAME, SAMPLE):
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("results"), list):
                data["source"] = "this machine" if src != SAMPLE else "sample shipped with Ember"
                return data
        except (OSError, json.JSONDecodeError):
            continue
    return {"results": [], "source": "none"}


def save(data_dir: Path, data: dict[str, Any]) -> None:
    file = data_dir / FILENAME
    tmp = file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(file)


def for_model(data: dict[str, Any], name: str) -> dict[str, Any] | None:
    base = name.split(":", 1)[0]
    return next((r for r in data.get("results", []) if r.get("model") == base and "error" not in r), None)


if __name__ == "__main__":
    out = run(os.environ.get("EMBER_OLLAMA_URL", "http://127.0.0.1:11434"))
    print(json.dumps(out, indent=1))
