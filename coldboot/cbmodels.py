#!/usr/bin/env python3
"""ColdBoot helper for Ollama models. Standard library only.

  cbmodels.py missing --spec models.json            names of models not in Ollama ("base X" / "custom X")
  cbmodels.py check   --spec models.json            PASS/FAIL lines; exit 1 on any FAIL
  cbmodels.py pull    NAME                          download one model (needs internet)
  cbmodels.py create  --spec models.json NAME       rebuild one custom model from its base
  cbmodels.py export  --store DIR --dest DIR NAMES  copy manifests + blobs out, sha256-checked
  cbmodels.py import  --src DIR --store DIR         copy missing manifests + blobs in, sha256-checked

Talks only to a loopback Ollama URL (env COLDBOOT_OLLAMA_URL, default http://127.0.0.1:11434).
Never deletes or overwrites anything in a model store.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

MAX_MODELS = 64
MAX_LAYERS = 64
MAX_JSON_BYTES = 4 * 1024 * 1024
CHUNK = 1024 * 1024
REGISTRY = "registry.ollama.ai"


class ModelError(Exception):
    """Anything that should stop the command with a clear message."""


def ollama_url() -> str:
    url = os.environ.get("COLDBOOT_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ModelError("COLDBOOT_OLLAMA_URL must be http on loopback")
    return url


def api(path: str, body: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    url = ollama_url() + path  # http + loopback only, checked in ollama_url()
    req = urllib.request.Request(url, data=data, method="GET" if body is None else "POST")  # noqa: S310
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310  # nosec B310
        raw = resp.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ModelError(f"reply from {path} too large")
    result = json.loads(raw.decode("utf-8") or "{}")
    if not isinstance(result, dict):
        raise ModelError(f"unexpected reply from {path}")
    if result.get("error"):
        raise ModelError(f"{path}: {result['error']}")
    return result


def full_name(name: str) -> str:
    return name if ":" in name else name + ":latest"


def load_spec(path: str) -> dict[str, Any]:
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not isinstance(spec.get("base"), list) or not isinstance(spec.get("custom"), list):
        raise ModelError("models.json needs 'base' and 'custom' lists")
    if len(spec["base"]) + len(spec["custom"]) > MAX_MODELS:
        raise ModelError("too many models in spec")
    return spec


def installed() -> set[str]:
    models = api("/api/tags", None, 10).get("models", [])
    return {full_name(str(m.get("name", ""))) for m in models[:1000]}


def cmd_missing(spec: dict[str, Any]) -> int:
    have = installed()
    for name in spec["base"]:
        if full_name(name) not in have:
            print(f"base {name}")
    for item in spec["custom"]:
        if full_name(item["name"]) not in have:
            print(f"custom {item['name']}")
    return 0


def num_ctx_of(name: str) -> str:
    params = str(api("/api/show", {"model": name}, 30).get("parameters", ""))
    for line in params.splitlines()[:200]:
        parts = line.split()
        if len(parts) == 2 and parts[0] == "num_ctx":
            return parts[1]
    return ""


def cmd_check(spec: dict[str, Any]) -> int:
    have = installed()
    failures = 0
    for name in spec["base"]:
        found = full_name(name) in have
        failures += 0 if found else 1
        print(f"{'PASS' if found else 'FAIL'} model {name}")
    for item in spec["custom"]:
        name = item["name"]
        if full_name(name) not in have:
            failures += 1
            print(f"FAIL model {name} (missing)")
            continue
        want = str(item["parameters"].get("num_ctx", ""))
        got = num_ctx_of(name)
        good = want == got
        failures += 0 if good else 1
        print(f"{'PASS' if good else 'FAIL'} model {name} (num_ctx {got or '?'}, want {want})")
    return 1 if failures else 0


def cmd_pull(name: str) -> int:
    api("/api/pull", {"model": name, "stream": False}, 6 * 3600)
    print(f"pulled {name}")
    return 0


def cmd_create(spec: dict[str, Any], name: str) -> int:
    for item in spec["custom"]:
        if item["name"] == name:
            body = {"model": name, "from": item["from"], "parameters": item["parameters"], "stream": False}
            api("/api/create", body, 600)
            print(f"created {name} from {item['from']}")
            return 0
    raise ModelError(f"{name} is not a custom model in the spec")


def manifest_path(store: Path, name: str) -> Path:
    repo, _, tag = full_name(name).partition(":")
    if "/" in repo or ".." in repo or "/" in tag or ".." in tag or not repo or not tag:
        raise ModelError(f"bad model name {name!r}")
    return store / "manifests" / REGISTRY / "library" / repo / tag


def digests(manifest: Path) -> list[str]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    layers = [data["config"], *data.get("layers", [])]
    if len(layers) > MAX_LAYERS:
        raise ModelError(f"too many layers in {manifest}")
    out = []
    for layer in layers:
        digest = str(layer["digest"])
        if (
            not digest.startswith("sha256:")
            or len(digest) != 71
            or not all(c in "0123456789abcdef" for c in digest[7:])
        ):
            raise ModelError(f"bad digest in {manifest}")
        out.append(digest[7:])
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_verified(src: Path, dst: Path, want: str) -> str:
    """Copy one blob unless an identical one is already there. Never overwrites a different file."""
    if dst.exists():
        if sha256_file(dst) != want:
            raise ModelError(f"existing {dst} has the wrong checksum; not touching it")
        return "kept"
    if not src.is_file():
        raise ModelError(f"missing blob {src}")
    part = dst.with_name(dst.name + ".part")
    shutil.copyfile(src, part)
    if sha256_file(part) != want:
        part.unlink()
        raise ModelError(f"CHECKSUM MISMATCH {src}")
    os.chmod(part, 0o644)
    part.replace(dst)
    return "copied"


def copy_model(src_store: Path, dst_store: Path, name: str) -> None:
    src_mf = manifest_path(src_store, name)
    if not src_mf.is_file():
        raise ModelError(f"no manifest for {name} in {src_store}")
    (dst_store / "blobs").mkdir(parents=True, exist_ok=True)
    for digest in digests(src_mf):
        blob = f"sha256-{digest}"
        state = copy_verified(src_store / "blobs" / blob, dst_store / "blobs" / blob, digest)
        print(f"  {state} {blob[:19]}")
    dst_mf = manifest_path(dst_store, name)
    if dst_mf.exists():
        if dst_mf.read_bytes() != src_mf.read_bytes():
            print(f"  kept existing (different) manifest for {name}")
        return
    dst_mf.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_mf, dst_mf)
    os.chmod(dst_mf, 0o644)
    print(f"done {name}")


def models_in(store: Path) -> list[str]:
    root = store / "manifests" / REGISTRY / "library"
    names = []
    for mf in sorted(root.glob("*/*"))[:MAX_MODELS]:
        if mf.is_file():
            names.append(f"{mf.parent.name}:{mf.name}")
    return names


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cbmodels")
    parser.add_argument("command", choices=["missing", "check", "pull", "create", "export", "import"])
    parser.add_argument("names", nargs="*")
    parser.add_argument("--spec")
    parser.add_argument("--store")
    parser.add_argument("--dest")
    parser.add_argument("--src")
    args = parser.parse_args(argv)
    if len(args.names) > MAX_MODELS:
        raise ModelError("too many names")
    if args.command in ("missing", "check", "create") and not args.spec:
        raise ModelError("--spec is required")
    if args.command == "missing":
        return cmd_missing(load_spec(args.spec))
    if args.command == "check":
        return cmd_check(load_spec(args.spec))
    if args.command in ("pull", "create") and len(args.names) != 1:
        raise ModelError("give exactly one model name")
    if args.command == "pull":
        return cmd_pull(args.names[0])
    if args.command == "create":
        return cmd_create(load_spec(args.spec), args.names[0])
    if args.command == "export":
        if not (args.store and args.dest and args.names):
            raise ModelError("export needs --store, --dest and model names")
        for name in args.names:
            print(f"export {name}")
            copy_model(Path(args.store), Path(args.dest), name)
        return 0
    if not (args.src and args.store):
        raise ModelError("import needs --src and --store")
    for name in models_in(Path(args.src)):
        print(f"import {name}")
        copy_model(Path(args.src), Path(args.store), name)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (ModelError, OSError, ValueError, KeyError) as exc:
        print(f"cbmodels: {exc}", file=sys.stderr)
        sys.exit(2)
