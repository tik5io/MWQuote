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
from pathlib import Path

from core.app_icon import ensure_icon_file, get_icon_path


def run(cmd):
    print(" ".join(cmd))
    subprocess.check_call(cmd)


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
