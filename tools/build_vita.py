#!/usr/bin/env python3
"""Build Orcs & Elves / Orcs & Elves II for PS Vita (.vpk) with Classic + Remastered lighting."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VITASDK = Path(os.environ.get("VITASDK", str(ROOT / "tools/vendor/vitasdk")))
BUILD_ROOT = ROOT / "build"
BUILD = BUILD_ROOT / "vita"

sys.path.insert(0, str(ROOT / "tools"))
from build_livearea import build_livearea_assets

GAME_CONFIG = {
    "oe1": {
        "title_id": "ORCS00001",
        "title_name": "Orcs & Elves",
        "data_files": {
            "orcsandelves.bar": "1411c7ad116fa58182488817f99f2a4efb59d7d1fb7d14090f6d072a93ef65cc",
            "orcsandelves.mod": "98f427593a75912fd88f500cc4e6624e7803c7cabc01778c378d6287fb3afbcf",
        },
        "engine_dir": ROOT / "src/engine/src/oe1",
        "cflags": ["-DGAME_OE1=1"],
        "vpk_name": "oe1.vpk",
        "install_dir": "ux0:data/oe1/",
    },
    "oe2": {
        "title_id": "ORCS00002",
        "title_name": "Orcs & Elves II",
        "data_files": {
            "orcsandelves2.bar": "508aa62a368cc77c64113a68c5485f43871bf18fa819a58ae8e3aac085265c2f",
            "orcsandelves2.mod": "1b8664e937ef8c43c474dff9b82c398b46425c5cca43eff5919e4ce96fc3d750",
        },
        "engine_dir": ROOT / "src/engine/src/oe2",
        "cflags": ["-DGAME_OE2=1"],
        "vpk_name": "oe2.vpk",
        "install_dir": "ux0:data/oe2/",
    },
}


def resolve_data_dir() -> Path:
    env = os.environ.get("OE2_DATA_DIR")
    if env:
        return Path(env)
    for p in (ROOT / "data", ROOT / "build/pc", ROOT / "gamedata"):
        if (p / "orcsandelves2.bar").is_file() or (p / "orcsandelves.bar").is_file():
            return p
    return ROOT / "data"


DATA_DIR = resolve_data_dir()


def verify_data(game: str):
    cfg = GAME_CONFIG[game]
    for name, sha in cfg["data_files"].items():
        path = DATA_DIR / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise RuntimeError(f"Missing or invalid {path} (expected BREW 7.0.41 asset)")


def setup_livearea(game: str, stage_dir: Path):
    assets_dir = ROOT / "src/vita/assets" / game
    sce_sys_dir = stage_dir / "sce_sys"
    if sce_sys_dir.exists():
        shutil.rmtree(sce_sys_dir)
    sce_sys_dir.mkdir(parents=True, exist_ok=True)

    bar_name = "orcsandelves.bar" if game == "oe1" else "orcsandelves2.bar"
    bar_path = DATA_DIR / bar_name
    if assets_dir.is_dir() and (assets_dir / "icon0.png").is_file():
        shutil.copytree(assets_dir, sce_sys_dir, dirs_exist_ok=True)
    elif bar_path.is_file():
        build_livearea_assets(bar_path, sce_sys_dir, game=game)
    else:
        legacy_assets = ROOT / "src/vita/assets"
        if game == "oe2" and legacy_assets.is_dir() and (legacy_assets / "icon0.png").is_file():
            shutil.copytree(legacy_assets, sce_sys_dir, dirs_exist_ok=True)
        else:
            raise RuntimeError(
                f"LiveArea assets not found in {assets_dir} and game data not found in {DATA_DIR}.\n"
                f"Run 'python3 tools/build_livearea.py --game {game}' with game data first."
            )


def sdl2_libs() -> list[str]:
    pc = VITASDK / "arm-vita-eabi/lib/pkgconfig/sdl2.pc"
    if pc.is_file():
        for line in pc.read_text(encoding="utf-8").splitlines():
            if line.startswith("Libs:"):
                return [tok for tok in line.split()[1:] if tok.startswith("-l")]
    return ["-lSDL2"]


def build_vita_game(game: str, bundle_data: bool = False):
    cfg = GAME_CONFIG[game]
    game_dir = cfg["engine_dir"]
    build_dir = BUILD / game
    stage_dir = build_dir / "vpk"
    obj_dir = build_dir / "obj"

    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    obj_dir.mkdir(parents=True, exist_ok=True)

    setup_livearea(game, stage_dir)

    gcc = VITASDK / "bin/arm-vita-eabi-gcc"
    elf_create = VITASDK / "bin/vita-elf-create"
    make_fself = VITASDK / "bin/vita-make-fself"
    mksfoex = VITASDK / "bin/vita-mksfoex"
    pack_vpk = VITASDK / "bin/vita-pack-vpk"

    for tool in (gcc, elf_create, make_fself, mksfoex, pack_vpk):
        if not tool.is_file():
            raise RuntimeError(f"Required VitaSDK tool not found: {tool}")

    game_sources = [
        ROOT / "src/engine/src/bar.c",
        ROOT / "src/engine/src/moddata.c",
        ROOT / "src/engine/src/pmd.c",
        ROOT / "src/engine/src/qcelp.c",
        *sorted(game_dir.glob("*.c")),
        ROOT / "src/vita/platform_vita.c",
        ROOT / "src/vita/main_vita.c",
    ]
    fast_math_sources = [
        ROOT / "src/host/lighting.c",
        ROOT / "src/host/presentation.c",
        ROOT / "src/host/standalone_bridge.c",
    ]

    elf_path = build_dir / f"{game}.elf"
    velf_path = build_dir / f"{game}.velf"
    eboot_path = stage_dir / "eboot.bin"
    sfo_path = stage_dir / "sce_sys/param.sfo"

    base_cflags = [
        "-std=gnu17",
        "-O3",
        "-mcpu=cortex-a9",
        "-mfpu=neon",
        "-mfloat-abi=hard",
        "-ftree-vectorize",
        "-fwrapv",
        "-funsigned-char",
        "-DOE2_STANDALONE_BRIDGE",
        "-DOE2_NO_SPRITE_SHADOWS",
        *cfg["cflags"],
        "-I" + str(ROOT / "src/engine/src"),
        "-I" + str(game_dir),
        "-I" + str(ROOT / "src/host"),
        "-I" + str(ROOT / "src/vita"),
        "-I" + str(VITASDK / "arm-vita-eabi/include/SDL2"),
    ]

    def compile_one(item):
        src, cflags = item
        obj = obj_dir / (src.stem + ".o")
        subprocess.run([str(gcc), *cflags, "-c", str(src), "-o", str(obj)], check=True)
        return obj

    tasks = [(s, base_cflags) for s in game_sources] + [
        (s, [*base_cflags, "-ffast-math", "-funroll-loops"]) for s in fast_math_sources
    ]
    with ThreadPoolExecutor() as ex:
        objects = list(ex.map(compile_one, tasks))

    libs = [*sdl2_libs(), "-lz", "-lm", "-lpthread"]
    if "-lvitaGL" in libs:
        libs.append("-lstdc++")
    for stub in (
        "-lSceDisplay_stub",
        "-lSceCtrl_stub",
        "-lSceAudio_stub",
        "-lSceAudioIn_stub",
        "-lSceSysmodule_stub",
        "-lSceGxm_stub",
        "-lSceCommonDialog_stub",
        "-lSceAppMgr_stub",
        "-lSceTouch_stub",
        "-lSceHid_stub",
        "-lSceMotion_stub",
        "-lScePower_stub",
        "-lSceProcessmgr_stub",
    ):
        if stub not in libs:
            libs.append(stub)

    subprocess.run([str(gcc), "-Wl,-q", *map(str, objects), *libs, "-o", str(elf_path)], check=True)
    subprocess.run([str(elf_create), str(elf_path), str(velf_path)], check=True)
    subprocess.run([str(make_fself), "-s", str(velf_path), str(eboot_path)], check=True)
    subprocess.run(
        [
            str(mksfoex),
            "-s",
            f"TITLE_ID={cfg['title_id']}",
            "-d",
            "ATTRIBUTE2=12",
            cfg["title_name"],
            str(sfo_path),
        ],
        check=True,
    )

    if bundle_data:
        stage_data = stage_dir / "data"
        stage_data.mkdir(parents=True, exist_ok=True)
        for name in cfg["data_files"]:
            shutil.copy2(DATA_DIR / name, stage_data / name)

    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    vpk_path = BUILD_ROOT / cfg["vpk_name"]
    if vpk_path.exists():
        vpk_path.unlink()
    subprocess.run([str(pack_vpk), "-s", str(sfo_path), "-b", str(eboot_path), str(vpk_path)], cwd=stage_dir, check=True)

    with zipfile.ZipFile(vpk_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(stage_dir.rglob("*")):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(stage_dir).as_posix())
    sha = hashlib.sha256(vpk_path.read_bytes()).hexdigest()
    print(f"Built {vpk_path} ({vpk_path.stat().st_size} bytes, SHA-256 {sha})")
    if bundle_data:
        print(f"[{cfg['title_name']}] Note: Game data was bundled in the VPK.")
    else:
        files_str = " and ".join(f"'{f}'" for f in cfg["data_files"])
        print(f"[{cfg['title_name']}] Note: Game data is NOT bundled in the VPK.")
        print(f"[{cfg['title_name']}] Note: Copy {files_str} to '{cfg['install_dir']}' in order to play.")


def parse_args():
    parser = argparse.ArgumentParser(description="Build Orcs & Elves / Orcs & Elves II for PS Vita (.vpk)")
    parser.add_argument(
        "--game",
        choices=["oe1", "oe2", "all"],
        default="all",
        help="Game edition to build (oe1, oe2, or all; default: all)",
    )
    parser.add_argument(
        "--bundle-data",
        action="store_true",
        help="Bundle .bar and .mod inside the VPK (only for private/testing builds, NOT for release)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    games = ["oe1", "oe2"] if args.game == "all" else [args.game]
    for game in games:
        if args.bundle_data:
            verify_data(game)
        build_vita_game(game, bundle_data=args.bundle_data)


if __name__ == "__main__":
    main()
