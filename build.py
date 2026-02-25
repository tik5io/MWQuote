#!/usr/bin/env python3
"""
Build MWQuote executable with PyInstaller.

Usage:
  python build.py
  python build.py --onefile
  python build.py --name MWQuote
"""

import argparse
import subprocess
import sys
import time
import shutil
from pathlib import Path
from datetime import datetime

from core.app_icon import ensure_icon_file, get_icon_path


def run(cmd):
    print(" ".join(cmd))
    subprocess.check_call(cmd)


def _kill_running_app(exe_name: str) -> None:
    """Best-effort stop of a running app that may lock dist output on Windows."""
    if sys.platform != "win32":
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/IM", exe_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _ensure_clean_dist_target(root: Path, app_name: str) -> Path | None:
    """
    Try to clear dist/<app_name>. If still locked, return a fallback dist path.
    """
    target = root / "dist" / app_name
    if not target.exists():
        return None

    for _ in range(3):
        try:
            shutil.rmtree(target)
            return None
        except PermissionError:
            _kill_running_app(f"{app_name}.exe")
            time.sleep(1.0)

    # Fallback: build into a fresh timestamped dist root to avoid locked folder.
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fallback = root / "dist_builds" / ts
    fallback.mkdir(parents=True, exist_ok=True)
    print(f"dist/{app_name} is locked; fallback output: {fallback}")
    return fallback


def main():
    root = Path(__file__).resolve().parent
    entry = root / "MainApp.py"
    if not entry.exists():
        print(f"Entry point not found: {entry}")
        return 1

    parser = argparse.ArgumentParser(description="Build MWQuote with PyInstaller")
    parser.add_argument("--onefile", action="store_true", help="Build a single-file executable")
    parser.add_argument("--name", default="MWQuote", help="Executable name")
    args = parser.parse_args()

    # Ensure icon exists
    ensure_icon_file()
    icon_path = get_icon_path()

    fallback_distpath = _ensure_clean_dist_target(root, args.name)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--name",
        args.name,
        "--add-data",
        "assets;assets",
        "--icon",
        str(icon_path),
        str(entry),
    ]

    if fallback_distpath is not None:
        cmd.extend(["--distpath", str(fallback_distpath)])

    if args.onefile:
        cmd.insert(4, "--onefile")
    else:
        cmd.insert(4, "--onedir")

    # Add noconsole to hide terminal window
    cmd.insert(4, "--noconsole")

    # Ensure logs folder is created at runtime if needed; no extra data packaged here.
    run(cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
