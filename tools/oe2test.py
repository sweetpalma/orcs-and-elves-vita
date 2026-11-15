#!/usr/bin/env python3
"""
tools/oe2test.py - Headless Testing and Screenshot Harness for Orcs & Elves I & II.

Controls PC game binaries (build/oe1, build/oe2) through the OE_PIPE harness
to automate gameplay sequences, verify game state and physics hashes, and capture
pixel-perfect 24-bit PNG screenshots.
"""

from __future__ import annotations

import argparse
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent

# Status parser for OE1 and OE2 pipe telemetry:
# S <tick> st <state> map <mapId> x <x> y <y> ang <ang> hp <hp>/<max> xp <xp> lvl <lvl> gold <gold> menu <menu> sel <sel> nitems <nitems> ... w <world_hash>
STATUS_RE = re.compile(
    r"^S\s+(?P<tick>\d+)\s+st\s+(?P<st>\d+)\s+map\s+(?P<map>\d+)\s+x\s+(?P<x>\d+)\s+y\s+(?P<y>\d+)\s+"
    r"ang\s+(?P<ang>\d+)\s+hp\s+(?P<hp>\d+)/(?P<max_hp>\d+)\s+xp\s+(?P<xp>\d+)\s+lvl\s+(?P<lvl>\d+)\s+"
    r"gold\s+(?P<gold>\d+)\s+menu\s+(?P<menu>\d+)\s+sel\s+(?P<sel>\d+)\s+nitems\s+(?P<nitems>\d+)"
)
HASH_RE = re.compile(r"w\s+([0-9a-fA-F]{8})")


def write_png24(path: Path, width: int, height: int, rgb_bytes: bytes) -> None:
    """Encode raw RGB24 bytes to a standard PNG file without external dependencies."""
    def chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)  # Filter type 0 (None)
        raw.extend(rgb_bytes[y * stride : (y + 1) * stride])

    idat = zlib.compress(bytes(raw), 6)
    png_data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_data)


def read_ppm(path: Path) -> Tuple[int, int, bytes]:
    """Parse binary P6 PPM framebuffer dumped by write_ppm()."""
    data = path.read_bytes()
    pos = 0
    tokens = []
    while len(tokens) < 4:
        while pos < len(data) and data[pos] in b" \t\r\n":
            pos += 1
        if pos < len(data) and data[pos : pos + 1] == b"#":
            while pos < len(data) and data[pos : pos + 1] != b"\n":
                pos += 1
            continue
        start = pos
        while pos < len(data) and data[pos] not in b" \t\r\n":
            pos += 1
        tokens.append(data[start:pos])

    magic, w_str, h_str, _ = tokens[:4]
    if magic != b"P6":
        raise ValueError(f"Invalid PPM magic: {magic}")
    w, h = int(w_str), int(h_str)
    while pos < len(data) and data[pos] in b" \t\r\n":
        pos += 1
    rgb = data[pos : pos + w * h * 3]
    return w, h, rgb


class GameSession:
    """Headless driver for Orcs & Elves PC engine via stdin/stdout pipe."""

    def __init__(
        self,
        game: str = "oe2",
        bin_path: Optional[Path] = None,
        screen: str = "352x200",
        fast: bool = True,
        data_dir: Optional[Path] = None,
    ):
        self.game = game.lower()
        if self.game not in ("oe1", "oe2"):
            raise ValueError(f"Invalid game: {game} (must be oe1 or oe2)")

        if bin_path is None:
            bin_path = ROOT_DIR / "build" / self.game
        self.bin_path = Path(bin_path)
        if not self.bin_path.is_file():
            raise FileNotFoundError(
                f"Binary not found: {self.bin_path}. Run 'python3 tools/build_pc.py --game {self.game}' first."
            )

        env = os.environ.copy()
        env["OE_PIPE"] = "1"
        env["SDL_VIDEODRIVER"] = "dummy"

        cmd = [str(self.bin_path), "--screen", screen]
        if fast:
            cmd.append("--fast")
        if data_dir:
            cmd.extend(["--data", str(data_dir)])

        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
            cwd=ROOT_DIR,
        )
        self.status = self._read_status()

    def _read_status(self) -> Dict[str, Any]:
        line = self.proc.stdout.readline()
        if not line:
            return {}
        line = line.strip()
        m = STATUS_RE.match(line)
        st_dict: Dict[str, Any] = {"raw": line}
        if m:
            for k, v in m.groupdict().items():
                st_dict[k] = int(v)
        m_w = HASH_RE.search(line)
        if m_w:
            st_dict["world_hash"] = m_w.group(1)
        return st_dict

    def step(self, cmd: str = "") -> Dict[str, Any]:
        """Send a single line command to the pipe harness and advance one tick."""
        if self.proc.poll() is not None:
            raise RuntimeError(f"Engine process terminated with return code {self.proc.returncode}")
        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()
        self.status = self._read_status()
        return self.status

    def ticks(self, count: int = 1) -> Dict[str, Any]:
        """Advance simulation by `count` ticks."""
        for _ in range(count):
            self.step()
        return self.status

    def wait_state(self, target_state: int, max_ticks: int = 100) -> Dict[str, Any]:
        """Tick until reaching `target_state`."""
        for _ in range(max_ticks):
            if self.status.get("st") == target_state:
                return self.status
            self.step()
        raise TimeoutError(f"Timed out waiting for state {target_state} (current: {self.status.get('st')})")

    def load_map(self, map_id: int, max_ticks: int = 100) -> Dict[str, Any]:
        """
        Load level and advance through travel map / intro animations until playing.
        Playing state: st=3 for both OE1 and OE2.
        """
        playing_state = 3
        self.step(f"map {map_id}")

        for _ in range(max_ticks):
            st = self.status.get("st")
            if st == playing_state:
                self.ticks(5)  # Allow spawn / fade timer to settle
                return self.status
            # In travel map (st=12 for OE1, st=11 for OE2), press select to confirm
            if (self.game == "oe1" and st == 12) or (self.game == "oe2" and st == 11):
                self.step("select")
            else:
                self.step()
        raise TimeoutError(f"Timed out loading map {map_id} (current state: {self.status.get('st')})")

    def teleport(self, x: int, y: int, ang: Optional[int] = None) -> Dict[str, Any]:
        """Teleport player to tile coordinates with optional angle."""
        if ang is not None:
            self.step(f"tp {x} {y} {ang}")
        else:
            self.step(f"tp {x} {y}")
        return self.ticks(2)

    def send_keys(self, *keys: str) -> Dict[str, Any]:
        """Send sequence of key names (one per tick)."""
        for k in keys:
            self.step(k)
        return self.status

    def dismiss_dialog(self, max_ticks: int = 50) -> Dict[str, Any]:
        """Dismiss active dialog messages (st=7) by pressing select."""
        for _ in range(max_ticks):
            if self.status.get("st") != 7:
                break
            self.step("select")
        return self.status

    def open_menu(self) -> Dict[str, Any]:
        """Press menu key (clr) to enter menu system (st=2)."""
        self.step("clr")
        for _ in range(20):
            if self.status.get("st") == 2:
                return self.status
            self.step()
        return self.status

    def screenshot(self, output_png: Path | str) -> Path:
        """Dump the current frame to a temporary PPM and save as 24-bit PNG."""
        output_png = Path(output_png)
        with tempfile.NamedTemporaryFile(suffix=".ppm", delete=False) as tmp:
            tmp_ppm = Path(tmp.name)
        try:
            self.step(f"shot {tmp_ppm}")
            w, h, rgb = read_ppm(tmp_ppm)
            write_png24(output_png, w, h, rgb)
        finally:
            if tmp_ppm.exists():
                tmp_ppm.unlink()
        return output_png

    def close(self) -> None:
        """Cleanly terminate the session."""
        if self.proc.poll() is None:
            try:
                self.proc.stdin.write("quit\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=2)
            except Exception:
                self.proc.kill()

    def __enter__(self) -> GameSession:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


def run_smoke_test(game: str, verbose: bool = True) -> bool:
    """Run automated smoke test suite verifying boot, level loading, turns, and menus."""
    if verbose:
        print(f"=== Running Smoke Test: {game.upper()} ===")
    t0 = time.time()
    try:
        with GameSession(game=game) as s:
            if verbose:
                print(f"  [1/6] Boot: tick={s.status.get('tick')}, state={s.status.get('st')}")
            assert s.status.get("st") == 0, f"Expected initial state 0, got {s.status.get('st')}"

            # Load map (Map 6001 for OE1, Map 9 for OE2)
            target_map = 6001 if game == "oe1" else 9
            playing_state = 3
            if verbose:
                print(f"  [2/6] Loading level {target_map}...")
            s.load_map(target_map)
            assert s.status.get("st") == playing_state, f"Expected state {playing_state}, got {s.status.get('st')}"
            assert s.status.get("hp", 0) > 0, "Player HP should be > 0"
            if s.status.get("st") == 7:
                s.dismiss_dialog()

            hash_start = s.status.get("world_hash")
            ang_start = s.status.get("ang", 0)
            if verbose:
                print(f"  [3/6] Playing: hp={s.status.get('hp')}/{s.status.get('max_hp')}, hash={hash_start}")

            # Turn left
            s.step("left")
            s.ticks(4)
            ang_after = s.status.get("ang", 0)
            assert ang_after != ang_start, f"Player angle did not rotate: {ang_start} -> {ang_after}"
            if verbose:
                print(f"  [4/6] Rotation check: ang {ang_start} -> {ang_after} (PASS)")

            # Open menu
            s.open_menu()
            assert s.status.get("st") == 2, f"Expected menu state 2, got {s.status.get('st')}"
            if verbose:
                print(f"  [5/6] Menu opened: menu={s.status.get('menu')}, sel={s.status.get('sel')} (PASS)")

            # Return to game
            s.step("clr")
            s.ticks(5)
            assert s.status.get("st") == playing_state, f"Expected return to playing {playing_state}, got {s.status.get('st')}"
            if verbose:
                print(f"  [6/6] Returned to gameplay: state={s.status.get('st')} (PASS)")

        elapsed = time.time() - t0
        if verbose:
            print(f"=== {game.upper()} Smoke Test: ALL CHECKS PASSED ({elapsed:.2f}s) ===\n")
        return True
    except Exception as e:
        if verbose:
            print(f"=== {game.upper()} Smoke Test FAILED: {e} ===\n")
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Headless test & screenshot driver for Orcs & Elves I & II")
    parser.add_argument("--game", choices=["oe1", "oe2", "all"], default="oe2", help="Game target (default: oe2)")
    parser.add_argument("--bin", type=Path, default=None, help="Explicit path to game binary")
    parser.add_argument("--map", type=int, default=None, help="Map ID to load")
    parser.add_argument("--tp", nargs="+", type=int, default=None, help="Teleport: <x> <y> [ang]")
    parser.add_argument("--keys", type=str, default=None, help="Comma-separated keys to send (e.g. 'select,right,right')")
    parser.add_argument("--ticks", type=int, default=5, help="Number of ticks to advance (default: 5)")
    parser.add_argument("--shot", type=Path, default=None, help="Save PNG screenshot to path")
    parser.add_argument("--smoke", action="store_true", help="Run automated smoke tests")
    parser.add_argument("--screen", type=str, default="352x200", help="Screen resolution (default: 352x200)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.smoke:
        games = ["oe1", "oe2"] if args.game == "all" else [args.game]
        all_passed = all(run_smoke_test(g) for g in games)
        return 0 if all_passed else 1

    game = "oe2" if args.game == "all" else args.game
    with GameSession(game=game, bin_path=args.bin, screen=args.screen) as s:
        if args.map is not None:
            print(f"Loading map {args.map}...")
            s.load_map(args.map)
        if args.tp:
            x = args.tp[0]
            y = args.tp[1]
            ang = args.tp[2] if len(args.tp) > 2 else None
            print(f"Teleporting to x={x}, y={y}, ang={ang}...")
            s.teleport(x, y, ang)
        if args.keys:
            key_list = [k.strip() for k in args.keys.split(",") if k.strip()]
            print(f"Sending keys: {key_list}")
            s.send_keys(*key_list)
        if args.ticks > 0:
            s.ticks(args.ticks)

        st = s.status
        print(
            f"State: tick={st.get('tick')}, st={st.get('st')}, map={st.get('map')}, "
            f"pos=({st.get('x')}, {st.get('y')}), ang={st.get('ang')}, "
            f"hp={st.get('hp')}/{st.get('max_hp')}, hash={st.get('world_hash')}"
        )

        if args.shot:
            out = s.screenshot(args.shot)
            print(f"Saved screenshot: {out} ({out.stat().st_size} bytes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
