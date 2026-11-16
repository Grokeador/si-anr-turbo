"""Recompile native x64 Smart-Shield nvngx_dlssg.dll using Zig Clang x64."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def find_zig() -> str | None:
    found = shutil.which("zig")
    if found:
        return found
    winget_zig = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "zig.exe"
    if winget_zig.exists():
        return str(winget_zig)
    return None


def main() -> None:
    zig = find_zig()
    if not zig:
        raise SystemExit("zig compiler not found on PATH or WinGet Links.")
    out_dir = HERE / "bin"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dll = out_dir / "nvngx_dlssg.dll"
    cmd = [
        zig, "cc",
        "-target", "x86_64-windows-gnu",
        "-shared", "-O2", "-Wall", "-Wextra", "-s",
        str(HERE / "nvngx_dlssg_shim.c"),
        str(HERE / "nvngx_dlssg.def"),
        "-o", str(out_dll),
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"Built {out_dll} ({out_dll.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
