#!/usr/bin/env python3
"""Build Orcs & Elves / Orcs & Elves II for native PC (SDL2) with Classic + Remastered lighting."""
from pathlib import Path
import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = ROOT / "build"

GAME_CONFIG = {
    "oe1": {
        "title": "Orcs & Elves",
        "data_files": {
            "orcsandelves.bar": "1411c7ad116fa58182488817f99f2a4efb59d7d1fb7d14090f6d072a93ef65cc",
            "orcsandelves.mod": "98f427593a75912fd88f500cc4e6624e7803c7cabc01778c378d6287fb3afbcf",
        },
        "target": "oe1",
    },
    "oe2": {
        "title": "Orcs & Elves II",
        "data_files": {
            "orcsandelves2.bar": "508aa62a368cc77c64113a68c5485f43871bf18fa819a58ae8e3aac085265c2f",
            "orcsandelves2.mod": "1b8664e937ef8c43c474dff9b82c398b46425c5cca43eff5919e4ce96fc3d750",
        },
        "target": "oe2",
    },
}


def resolve_data_dir() -> Path:
    env = os.environ.get("OE_DATA_DIR")
    if env:
        return Path(env)
    for p in (ROOT / "data", ROOT / "build/pc", ROOT / "gamedata"):
        if (p / "orcsandelves2.bar").is_file() or (p / "orcsandelves.bar").is_file():
            return p
    return ROOT / "data"


DATA_DIR = resolve_data_dir()


def verify_data(game: str) -> bool:
    expected = GAME_CONFIG[game]["data_files"]
    has_data = True
    for name, sha in expected.items():
        path = DATA_DIR / name
        if not path.is_file():
            has_data = False
            break
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            print(f"Warning: {path} does not match expected BREW 7.0.41 checksum")
    return has_data


def parse_args():
    parser = argparse.ArgumentParser(description="Build Orcs & Elves / Orcs & Elves II for PC (SDL2)")
    parser.add_argument(
        "--game",
        choices=["oe1", "oe2", "all"],
        default="all",
        help="Game edition to build (oe1, oe2, or all; default: all)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    games = ["oe1", "oe2"] if args.game == "all" else [args.game]

    for game in games:
        verify_data(game)

    cmake = shutil.which("cmake")
    if not cmake:
        raise RuntimeError("cmake not found in PATH")

    arch = platform.machine().lower() or "unknown"
    build_dir = BUILD_ROOT / "pc" / f"{sys.platform}-{arch}"
    subprocess.run([cmake, "-S", str(ROOT / "src/engine"), "-B", str(build_dir)], check=True)
    subprocess.run([cmake, "--build", str(build_dir), "--parallel"], check=True)

    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    for game in games:
        cfg = GAME_CONFIG[game]
        base_name = cfg["target"]
        exe_name = f"{base_name}.exe" if sys.platform == "win32" else base_name
        src_bin = build_dir / "src" / exe_name
        if not src_bin.is_file():
            raise RuntimeError(f"Expected built executable at {src_bin}")

        dst_bin = BUILD_ROOT / exe_name
        shutil.copy2(src_bin, dst_bin)
        sha = hashlib.sha256(dst_bin.read_bytes()).hexdigest()
        print(f"[{cfg['title']}] Built {dst_bin} ({dst_bin.stat().st_size} bytes, SHA-256 {sha})")
        files_str = ", ".join(cfg["data_files"].keys())
        print(f"[{cfg['title']}] Note: Ship data files ({files_str}) inside \"data\" folder together with the executable.")


if __name__ == "__main__":
    main()
