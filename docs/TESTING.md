# Automated Testing & Screenshot Harness

This document describes the headless testing infrastructure, command line driver, and Python API for _Orcs & Elves_ (`oe1`) and _Orcs & Elves II_ (`oe2`).

The test framework is powered by `tools/oe2test.py` and interacts directly with the deterministic pipe harness built into the native PC engine binaries (`src/engine/src/main.c`).

## 1. Overview

Testing game logic, UI formatting, and lighting rendering across two separate games usually requires manual playthroughs. To automate this:

1. **Headless Execution**: The engine runs without audio or video display servers (`SDL_VIDEODRIVER=dummy`).
2. **Lock-Step Pipe Harness (`OE_PIPE=1`)**: The engine prints telemetry before each tick, reads an instruction from `stdin`, runs the tick, and repeats deterministically.
3. **Automated Frame Captures**: The engine dumps raw 16-bit framebuffers to PPM via the `shot` command; `tools/oe2test.py` automatically converts them into 24-bit PNGs without any external dependencies (using pure Python standard library `zlib` and `struct`).
4. **State & Regression Checking**: A 32-bit FNV-1a checksum (`world_hash`) tracks random pool state, entity positions, parameters, and health to detect gameplay desyncs.

## 2. CLI Tool: `tools/oe2test.py`

`tools/oe2test.py` provides high-level command-line flags to run smoke tests, teleport the player, send key sequences, and capture PNG screenshots.

### Running Automated Smoke Tests

Runs a fast (<1s) end-to-end check verifying engine startup, level loading, movement, rotation, pause menu handling, and clean gameplay resumption:

```sh
# Test both games:
python3 tools/oe2test.py --smoke --game all

# Test a specific game:
python3 tools/oe2test.py --smoke --game oe1
python3 tools/oe2test.py --smoke --game oe2
```

Sample output:

```text
=== Running Smoke Test: OE1 ===
  [1/6] Boot: tick=0, state=0
  [2/6] Loading level 6001...
  [3/6] Playing: hp=100/100, hash=85a66cc7
  [4/6] Rotation check: ang 768 -> 0 (PASS)
  [5/6] Menu opened: menu=100, sel=1 (PASS)
  [6/6] Returned to gameplay: state=3 (PASS)
=== OE1 Smoke Test: ALL CHECKS PASSED (0.35s) ===

=== Running Smoke Test: OE2 ===
  [1/6] Boot: tick=0, state=0
  [2/6] Loading level 9...
  [3/6] Playing: hp=100/100, hash=f7170167
  [4/6] Rotation check: ang 256 -> 512 (PASS)
  [5/6] Menu opened: menu=100, sel=1 (PASS)
  [6/6] Returned to gameplay: state=3 (PASS)
=== OE2 Smoke Test: ALL CHECKS PASSED (0.31s) ===
```

### Capturing Screenshots

Capture high-resolution PNG screenshots from any level, position, and orientation:

```sh
# OE1: Capture Level 1 starting courtyard
python3 tools/oe2test.py --game oe1 --map 6001 --tp 10 10 256 --shot /tmp/oe1_courtyard.png

# OE2: Capture Hub Room (Level 9) crystal dais facing north
python3 tools/oe2test.py --game oe2 --map 9 --tp 11 14 256 --shot /tmp/oe2_hub_crystals.png

# OE2: Capture Hub Room portals
python3 tools/oe2test.py --game oe2 --map 9 --tp 13 8 768 --shot /tmp/oe2_hub_portals.png
```

#### CLI Options Reference

| Flag           | Argument            | Description                                                                                               |
| :------------- | :------------------ | :-------------------------------------------------------------------------------------------------------- |
| **`--game`**   | `oe1`, `oe2`, `all` | Target game engine (default: `oe2`).                                                                      |
| **`--smoke`**  | _none_              | Run the automated smoke test suite.                                                                       |
| **`--map`**    | `<id>`              | Level map ID to load (`6001`–`6011` for OE1, `1`–`9` for OE2).                                            |
| **`--tp`**     | `<x> <y> [ang]`     | Teleport player to tile coordinates with optional angle (`0`=East, `256`=North, `512`=West, `768`=South). |
| **`--keys`**   | `<k1,k2,...>`       | Comma-separated list of keys to send (e.g. `--keys "up,up,select"`).                                      |
| **`--ticks`**  | `<n>`               | Number of simulation ticks to advance (default: `5`).                                                     |
| **`--shot`**   | `<path.png>`        | File path where the captured PNG screenshot should be saved.                                              |
| **`--screen`** | `WxH`               | Framebuffer resolution (default: `352x200`).                                                              |
| **`--bin`**    | `<path>`            | Custom path to the executable (default: `build/oe1` or `build/oe2`).                                      |

## 3. Python API Reference (`GameSession`)

You can import `GameSession` directly into Python scripts to write custom test runners or visual inspection tools.

### Basic Usage

```python
from tools.oe2test import GameSession

with GameSession(game="oe2") as session:
    session.load_map(9)
    session.teleport(11, 14, 256)
    session.screenshot("hub_view.png")
```

### Methods

#### `GameSession(game="oe2", bin_path=None, screen="352x200", fast=True, data_dir=None)`

Starts the headless game process and reads the initial boot telemetry.

- Supported games: `"oe1"`, `"oe2"`.
- `fast=True`: Runs with `--fast` (fast tick timer).

#### `session.step(cmd="") -> dict`

Sends a single command or key to the engine and advances simulation by exactly one tick. Returns parsed status dictionary.

#### `session.ticks(count=1) -> dict`

Advances the simulation by `count` ticks without sending input.

#### `session.load_map(map_id: int) -> dict`

Sends the `map <id>` command, handles travel-map confirmation prompts (`select`) if necessary, and waits until the game reaches active playing state (`st=3`). Allows spawn animations to settle.

#### `session.teleport(x: int, y: int, ang: Optional[int] = None) -> dict`

Teleports the player to tile `(x, y)` facing `ang` (0..1023).

#### `session.send_keys(*keys: str) -> dict`

Sends a sequence of key names in consecutive ticks. Available keys:

- `up`, `down`, `left`, `right`
- `select` (Use / Attack / Confirm)
- `soft1` (Left Softkey), `soft2` (Right Softkey)
- `clr` (Clear / Pause Menu)
- `star`, `pound`
- `0` through `9`

#### `session.open_menu() -> dict`

Sends the pause key (`clr`) and waits until state transitions to menu (`st=2`).

#### `session.dismiss_dialog(max_ticks=50) -> dict`

Dismisses any active dialogue messages (`st=7`) by advancing with `select`.

#### `session.screenshot(output_png: Path | str) -> Path`

Dumps the current frame buffer and writes a 24-bit PNG to `output_png`.

#### `session.status -> dict`

Dictionary holding current telemetry parsed from the status line:

- `tick`: Current engine tick count
- `st`: Canvas state (0 = Title/Logos, 2 = Menu, 3 = Playing, 6 = Loading, 7 = Dialogue, 11/12 = Travel Map, 17 = Cinematic)
- `map`: Current level ID
- `x`, `y`: Player tile coordinates
- `ang`: Facing angle (0..1023)
- `hp`, `max_hp`: Player current and max health
- `xp`, `lvl`, `gold`: Progression stats
- `menu`, `sel`, `nitems`: Active menu ID, selected item index, item count
- `world_hash`: 8-digit hex FNV-1a checksum of the world simulation
- `raw`: Full unparsed telemetry line

## 4. Python Script Examples

### Example 1: Testing Menu Navigation & Line Wrapping

```python
from tools.oe2test import GameSession

with GameSession(game="oe1") as s:
    s.load_map(6001)
    s.open_menu()               # Opens Pause Menu (100)
    s.step("select")            # Opens Items Menu (500)
    s.step("up")                # Selects 'Back' item
    s.screenshot("oe1_menu_test.png")

    assert s.status["menu"] == 500
    assert s.status["sel"] == 0
    print("Items menu verified successfully!")
```

### Example 2: Verifying Combat & Health Deduction

```python
from tools.oe2test import GameSession

with GameSession(game="oe2") as s:
    s.load_map(2)
    start_hp = s.status["hp"]

    # Teleport near an enemy and wait for attack
    s.teleport(5, 12, 0)
    s.ticks(20)

    print(f"Health: {start_hp} -> {s.status['hp']}")
    assert s.status["hp"] <= start_hp
```

### Example 3: Verifying Remastered Lighting Rendering

```python
import os
from tools.oe2test import GameSession

# Force remastered dynamic lighting
os.environ["OE_REMASTERED"] = "1"

with GameSession(game="oe2") as s:
    s.load_map(9)
    s.teleport(11, 14, 256)
    s.screenshot("remastered_lighting.png")
```

## 5. Technical Details: Pipe Protocol

When `OE_PIPE=1` is passed in the environment:

1. **Engine Output (Stdout)**:
   ```text
   S <tick> st <state> map <mapId> x <tileX> y <tileY> ang <angle> hp <hp>/<max> xp <xp> lvl <lvl> gold <gold> menu <menuId> sel <selIndex> nitems <numItems> ... w <world_hash>
   ```
2. **Engine Input (Stdin)**:
   - `\n` (empty line): Advances game simulation by 1 tick.
   - `<key>`: Presses key for that tick.
   - `tp <x> <y> [ang]`: Instant teleportation.
   - `map <id>`: Instant map transition.
   - `shot <file.ppm>`: Dumps the rendered 16-bit framebuffer to `<file.ppm>`.
   - `god`, `noclip`: Toggles cheat modes.
   - `quit`: Closes the game cleanly.
