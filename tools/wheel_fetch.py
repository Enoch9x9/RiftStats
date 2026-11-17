"""Download wheels from PyPI without pip, extract them into a target dir.

pip's unpack step is blocked by the local sandbox (EACCES on the transient
`*.whl.metadata` file), so we do the same job with urllib + zipfile.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WHEELS = ROOT / ".tmp" / "wheels"
LIBS = ROOT / "libs"

TAGS = ("cp310-abi3-win_amd64", "cp312-cp312-win_amd64", "py3-none-any")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "riftstats-setup"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def pick_wheel(name: str, version: str | None = None) -> tuple[str, str]:
    meta = json.loads(_get(f"https://pypi.org/pypi/{name}/json"))
    version = version or meta["info"]["version"]
    files = meta["releases"].get(version) or []
    cands = [f for f in files if f["filename"].endswith(".whl")]
    for tag in TAGS:
        for f in cands:
            if tag in f["filename"]:
                return f["filename"], f["url"]
    for f in cands:  # Windows fallback: any win_amd64 wheel
        if "win_amd64" in f["filename"]:
            return f["filename"], f["url"]
    raise RuntimeError(f"no wheel for {name}=={version}")


def download(name: str, version: str | None = None) -> Path:
    WHEELS.mkdir(parents=True, exist_ok=True)
    filename, url = pick_wheel(name, version)
    dest = WHEELS / filename
    if not dest.exists() or dest.stat().st_size == 0:
        print(f"  fetching {filename}")
        data = _get(url)
        dest.write_bytes(data)
    print(f"  have     {filename} ({dest.stat().st_size/1e6:.1f} MB)")
    return dest


def requirements(wheel: Path) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    with zipfile.ZipFile(wheel) as zf:
        meta = [n for n in zf.namelist() if n.endswith(".dist-info/METADATA")]
        if not meta:
            return out
        for line in zf.read(meta[0]).decode("utf-8", "ignore").splitlines():
            if not line.startswith("Requires-Dist:"):
                continue
            spec = line.split(":", 1)[1].strip()
            if "extra ==" in spec:
                continue
            m = re.match(r"([A-Za-z0-9_.\-]+)\s*(?:\(([^)]*)\))?", spec)
            if not m:
                continue
            ver = None
            if m.group(2):
                ver = re.sub(r"[^0-9.]", "", m.group(2))
            out.append((m.group(1).replace("_", "-"), ver))
    return out


def extract(wheel: Path) -> None:
    LIBS.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel) as zf:
        zf.extractall(LIBS)


def main(roots: list[str]) -> None:
    seen: set[str] = set()
    queue: list[tuple[str, str | None]] = [(r, None) for r in roots]
    while queue:
        name, ver = queue.pop(0)
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        print(f"[dep] {name}")
        wheel = download(name, ver)
        for dep, dver in requirements(wheel):
            if dep.lower() not in seen:
                queue.append((dep, dver))
        extract(wheel)
    print("done ->", LIBS)


if __name__ == "__main__":
    main(sys.argv[1:] or ["PySide6"])
