#!/usr/bin/env python3
"""ColdBoot helper: put Matt's project repos and their build dependencies in the cache.

Called by `coldboot.sh cache` (online, on the P1). Reads coldboot/projects-seed.json
and the bare mirrors in ~/git (scripts/import-mirrors.sh). Writes, under DEST:
  repos/NAME.bundle, repos/issues/*.json   every mirror, all branches and tags
  buildhost/pio-envs/CORE/                 one PlatformIO core per platform version (toolchains,
                                           frameworks, boards); use with PLATFORMIO_CORE_DIR
  projects/NAME/libdeps/                   the project's exact library versions (.pio/libdeps)
  projects/wheels/{linux,windows}/         Python 3.12 wheels for every requirements file
  projects/npm-cache/                      npm cache for every npm folder (Linux + Windows)
  projects/nuget.tar.gz                    NuGet packages made on Los Gatos (nuget-offline.ps1)
  projects/MANIFEST.json                   what was cached, versions, sizes, problems
Standard library only; every command is an argument list with a timeout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess  # nosec B404 - fixed argument lists, no shell
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

CMD_TIMEOUT = 3600
PY = "3.12"
GIT = shutil.which("git") or "/usr/bin/git"
PLATFORMS = {
    "linux": ("x86_64-manylinux_2_28", ["manylinux_2_28_x86_64", "manylinux_2_17_x86_64", "manylinux2014_x86_64"]),
    "windows": ("x86_64-pc-windows-msvc", ["win_amd64"]),
}


def lib_version(folder: Path) -> str:
    meta, props = folder / "library.json", folder / "library.properties"
    if meta.is_file():
        return str(json.loads(meta.read_text()).get("version", "?"))
    if props.is_file():
        for line in props.read_text(errors="replace").splitlines():
            if line.startswith("version="):
                return line[8:].strip()
    return "?"


class Cache:
    def __init__(self, args: argparse.Namespace) -> None:
        self.dest: Path = args.dest
        self.git_dir: Path = args.git_dir
        self.pio: str = args.pio
        self.python: str = args.python
        self.uv: str = args.uv
        self.node_tgz: Path | None = args.node_tgz
        self.nuget: Path = args.nuget
        self.scratch = Path(tempfile.mkdtemp(prefix="cb-projects."))
        self.manifest: dict[str, Any] = {"repos": {}, "platformio": {}, "wheels": {}, "npm": {}, "problems": []}

    def run(self, args: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> bool:
        res = subprocess.run(  # noqa: S603 # nosec B603 - argument list from this script
            args, cwd=cwd, env=env, capture_output=True, text=True, timeout=CMD_TIMEOUT, check=False
        )
        if res.returncode != 0:
            tail = (res.stderr or res.stdout).strip().splitlines()[-3:]
            self.problem(f"{' '.join(args[:4])}: {' | '.join(tail)[:300]}")
        return res.returncode == 0

    def problem(self, text: str) -> None:
        print(f"  WARN  {text}")
        self.manifest["problems"].append(text)

    def mirror(self, repo: str) -> Path | None:
        bare = self.git_dir / f"{repo.rsplit('/', 1)[-1]}.git"
        return bare if bare.is_dir() else None

    def checkout(self, name: str, bare: Path) -> Path | None:
        work = self.scratch / name
        return work if self.run([GIT, "clone", "-q", str(bare), str(work)]) else None

    # ---- repos ----
    def repos(self) -> None:
        out = self.dest / "repos"
        (out / "issues").mkdir(parents=True, exist_ok=True)
        for bare in sorted(self.git_dir.glob("*.git")):
            bundle = out / f"{bare.stem}.bundle"
            if self.run([GIT, "-C", str(bare), "bundle", "create", str(bundle), "--all"]):
                self.manifest["repos"][bare.stem] = bundle.stat().st_size
        for j in sorted((self.git_dir / "issues").glob("*.json")):
            shutil.copy2(j, out / "issues" / j.name)
        print(f"  ok    {len(self.manifest['repos'])} repo bundles")

    # ---- PlatformIO ----
    @staticmethod
    def core_name(platform: str, packages: list[str]) -> str:
        """One PlatformIO core dir per platform version: two Arduino-ESP32 versions can't share one."""
        if platform.startswith("https://"):
            ver = next((p for p in platform.split("/") if p[:1].isdigit()), "url")
            digest = hashlib.sha1((platform + "|".join(packages)).encode(), usedforsecurity=False).hexdigest()[:6]
            return f"pioarduino-{ver}-{digest}"
        return re.sub(r"[^A-Za-z0-9@._-]", "_", platform) or "default"

    def env_groups(self, work: Path) -> dict[str, list[str]]:
        res = subprocess.run(  # noqa: S603 # nosec B603
            [self.pio, "project", "config", "--json-output"],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        groups: dict[str, list[str]] = {}
        try:
            sections = json.loads(res.stdout)
        except json.JSONDecodeError:
            self.problem(f"{work.name}: could not read platformio.ini")
            return groups
        for section, items in sections:
            if not section.startswith("env:"):
                continue
            opts = dict(items)
            pkgs = opts.get("platform_packages", [])
            pkgs = [pkgs] if isinstance(pkgs, str) else list(pkgs)
            groups.setdefault(self.core_name(str(opts.get("platform", "")), pkgs), []).append(section[4:])
        return groups

    def platformio(self, proj: dict[str, Any], work: Path) -> None:
        cores = self.dest / "buildhost" / "pio-envs"
        info: dict[str, Any] = {}
        for core, envs in self.env_groups(work).items():
            env = dict(os.environ, PLATFORMIO_CORE_DIR=str(cores / core))
            for name in envs:
                ok = self.run([self.pio, "pkg", "install", "-s", "-e", name], cwd=work, env=env)
                # A full build once online: pioarduino fetches some packages only while building.
                built = ok and core != "native" and self.run([self.pio, "run", "-s", "-e", name], cwd=work, env=env)
                info[name] = {"core": f"buildhost/pio-envs/{core}", "built_online": built}
            (cores / core / ".ember-core-path").write_text(str(cores / core))
            shutil.rmtree(cores / core / ".cache", ignore_errors=True)
        libdeps = work / ".pio" / "libdeps"
        target = self.dest / "projects" / proj["name"] / "libdeps"
        if libdeps.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(libdeps, target)
        versions = {}
        for d in sorted(p for p in target.glob("*/*") if p.is_dir()) if target.is_dir() else []:
            versions[f"{d.parent.name}/{d.name}"] = lib_version(d)
        self.manifest["platformio"][proj["name"]] = {"envs": info, "libdeps": versions}
        print(f"  ok    {proj['name']}: PlatformIO envs {', '.join(info)}")

    # ---- Python wheels ----
    def wheels(self, proj: dict[str, Any], bare: Path, req_path: str) -> None:
        req = self.scratch / f"{proj['name']}-{req_path.replace('/', '_')}"
        res = subprocess.run(  # noqa: S603 # nosec B603
            [GIT, "-C", str(bare), "show", f"HEAD:{req_path}"], capture_output=True, timeout=60, check=False
        )
        if res.returncode != 0:
            self.problem(f"{proj['name']}: no {req_path} in the mirror")
            return
        req.write_bytes(res.stdout)
        for plat, (uv_plat, tags) in PLATFORMS.items():
            lock = req.with_suffix(f".{plat}.lock")
            if not self.run(
                [
                    self.uv,
                    "pip",
                    "compile",
                    "-q",
                    "--python-version",
                    PY,
                    "--python-platform",
                    uv_plat,
                    "--no-header",
                    "--no-annotate",
                    str(req),
                    "-o",
                    str(lock),
                ]
            ):
                continue
            plat_args = [a for t in tags for a in ("--platform", t)]
            ok = self.run(
                [
                    self.python,
                    "-m",
                    "pip",
                    "download",
                    "-q",
                    "--no-deps",
                    "--only-binary=:all:",
                    "--python-version",
                    PY,
                    "--implementation",
                    "cp",
                    *plat_args,
                    "-r",
                    str(lock),
                    "-d",
                    str(self.dest / "projects" / "wheels" / plat),
                ]
            )
            if not ok:  # fall back to one package at a time so one sdist-only package does not block the rest
                for line in lock.read_text().splitlines():
                    if line and not line.startswith(("#", " ")):
                        self.run(
                            [
                                self.python,
                                "-m",
                                "pip",
                                "download",
                                "-q",
                                "--no-deps",
                                "--python-version",
                                PY,
                                "--implementation",
                                "cp",
                                *plat_args,
                                line.split(";")[0].strip(),
                                "-d",
                                str(self.dest / "projects" / "wheels" / plat),
                            ]
                        )
            shutil.copy2(lock, self.dest / "projects" / "wheels" / f"{proj['name']}-{lock.name.split('-', 1)[1]}")
        self.manifest["wheels"].setdefault(proj["name"], []).append(req_path)
        print(f"  ok    {proj['name']}: wheels for {req_path} (Linux + Windows, Python {PY})")

    # ---- npm ----
    def node_bin(self) -> Path | None:
        if self.node_tgz is None or not self.node_tgz.is_file():
            return None
        out = self.scratch / "node"
        if not out.is_dir():
            with tarfile.open(self.node_tgz) as tar:
                tar.extractall(out, filter="data")  # nosec B202 - pinned, checksum-verified Node tarball
        found = sorted(out.glob("node-*/bin"))
        return found[0] if found else None

    def npm(self, proj: dict[str, Any], work: Path, folder: str) -> None:
        bin_dir = self.node_bin()
        if bin_dir is None:
            self.problem(f"{proj['name']}: no Node tarball, npm cache skipped")
            return
        env = dict(os.environ, PATH=f"{bin_dir}:{os.environ.get('PATH', '')}")
        cache = str(self.dest / "projects" / "npm-cache")
        base = [str(bin_dir / "npm"), "ci", "--cache", cache, "--ignore-scripts", "--no-audit", "--no-fund"]
        ok = self.run(base, cwd=work / folder, env=env)
        ok = self.run([*base, "--os=win32", "--cpu=x64"], cwd=work / folder, env=env) and ok
        self.manifest["npm"].setdefault(proj["name"], []).append({"folder": folder, "ok": ok})
        print(f"  ok    {proj['name']}: npm cache for {folder}")

    def run_all(self, seed: Path) -> int:
        self.repos()
        projects = json.loads(seed.read_text())["projects"]
        for proj in projects:
            offline = proj.get("offline", {})
            template = offline.get("template")
            if template:  # planned project with no repo yet: build the template in the Ember repo
                work = self.scratch / proj["name"]
                shutil.copytree(Path(__file__).resolve().parent.parent / template, work)
                self.platformio(proj, work)
                continue
            bare = self.mirror(proj.get("repo", ""))
            if bare is None:
                if offline:
                    self.problem(f"{proj['name']}: no mirror in {self.git_dir} (run scripts/import-mirrors.sh)")
                continue
            for req_path in offline.get("pip", []):
                self.wheels(proj, bare, req_path)
            if offline.get("platformio") or offline.get("npm"):
                work = self.checkout(proj["name"], bare)
                if work is None:
                    continue
                if offline.get("platformio") and (work / "platformio.ini").is_file():
                    self.platformio(proj, work)
                for folder in offline.get("npm", []):
                    self.npm(proj, work, folder)
        if self.nuget.is_file():
            shutil.copy2(self.nuget, self.dest / "projects" / "nuget.tar.gz")
            self.manifest["nuget"] = self.nuget.stat().st_size
            print("  ok    NuGet packages from Los Gatos")
        else:
            self.problem(f"no {self.nuget} (run scripts/windows/nuget-offline.ps1 on Los Gatos)")
        out = self.dest / "projects" / "MANIFEST.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.manifest, indent=2))
        shutil.rmtree(self.scratch, ignore_errors=True)
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dest", type=Path, required=True)
    ap.add_argument("--seed", type=Path, default=Path(__file__).with_name("projects-seed.json"))
    ap.add_argument("--git-dir", type=Path, default=Path.home() / "git")
    ap.add_argument("--pio", default="pio")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--uv", default="uv")
    ap.add_argument("--node-tgz", type=Path, default=None)
    ap.add_argument("--nuget", type=Path, default=Path.home() / "offline" / "nuget.tar.gz")
    args = ap.parse_args()
    args.dest = args.dest.resolve()
    return Cache(args).run_all(args.seed)


if __name__ == "__main__":
    raise SystemExit(main())
