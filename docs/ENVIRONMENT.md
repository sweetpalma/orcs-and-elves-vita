# Environment & Build Variables

This document provides a reference for all environment variables, compile-time flags, and CLI parameters used across the build toolchain, PC test runner, and PS Vita port for both _Orcs & Elves_ (`oe1`) and _Orcs & Elves II_ (`oe2`).

## 1. Build Environment Variables

These variables are inspected by the Python build scripts and Docker containers:

| Variable          | Default                               | Description                                                                                                 |
| :---------------- | :------------------------------------ | :---------------------------------------------------------------------------------------------------------- |
| **`OE_DATA_DIR`** | `data/` (or `build/pc/`, `gamedata/`) | Directory containing original game archives (`orcsandelves.bar` / `.mod` and `orcsandelves2.bar` / `.mod`). |
| **`VITASDK`**     | `tools/vendor/vitasdk`                | Root installation path of the VitaSDK toolchain containing `arm-vita-eabi-*` binaries and sysroot.          |

## 2. Python Build Script CLI Options

### `tools/build_pc.py` (Native PC Build)

Automates CMake configuration and compilation for the host machine (macOS, Linux, Windows):

```sh
python3 tools/build_pc.py [--game {oe1, oe2, all}]
```

- **`--game`**: Selects target game binary to build (`oe1`, `oe2`, or `all`; default: `all`).

### `tools/build_vita.py` (PS Vita .VPK Package)

Builds PlayStation Vita executable binaries, generates LiveArea assets, and packages installable `.vpk` bundles:

```sh
python3 tools/build_vita.py [--game {oe1, oe2, all}] [--bundle-data]
```

- **`--game`**: Selects target game package (`oe1`, `oe2`, or `all`; default: `all`).
- **`--bundle-data`**: Embeds `.bar` and `.mod` assets directly into `app0:` inside the VPK. (For private test builds only; official distribution requires placing user-provided files into `ux0:data/oe1/` and `ux0:data/oe2/`).

## 3. Compile-Time Definitions (`-D...`)

These macros configure features in the engine, host bridge, and lighting subsystems during compilation:

| Macro                      | Component     | Description                                                                                                                                                                                  |
| :------------------------- | :------------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`OE_STANDALONE_BRIDGE`** | Engine / Host | Enables the host presentation layer: software framebuffer hooks, Remastered lighting passes, and Options menu controls.                                                                      |
| **`OE_NO_SPRITE_SHADOWS`** | Lighting      | Performance optimization for Vita and embedded targets: caches static wall/candle/lava geometry and skips per-frame dynamic sprite occluder rebuilds while preserving full wall ray shadows. |
| **`OE_LIGHT_MT`**          | Lighting      | Enables multi-threaded lighting worker support.                                                                                                                                              |
| **`OE_QA_INTERACTIONS`**   | Host / Tests  | Exposes internal diagnostic profiling counters (`profile[]`), radius verification, and test ray hooks.                                                                                       |
| **`OE_CINEMATIC_CAPTURE`** | Host          | Enables frame-capture hooks during scripted cutscenes.                                                                                                                                       |
| **`GAME_OE1`**             | Engine        | Compiles game logic, entity structures, and assets for _Orcs & Elves_ (Map IDs 6000–6011).                                                                                                   |
| **`GAME_OE2`**             | Engine        | Compiles game logic, entity structures, and assets for _Orcs & Elves II_ (Map IDs 1001–1007).                                                                                                |

### CMake Option (PC)

- **`OE_SANITIZE`** (`ON` / `OFF`, default: `OFF`): Builds binaries with Clang/GCC AddressSanitizer and UndefinedBehaviorSanitizer (`-fsanitize=address,undefined`).

## 4. Runtime Environment Variables

The standalone PC runner (`build/oe1` and `build/oe2`) recognizes several runtime environment variables for automated testing, debugging, and visual verification:

### Presentation & Gameplay

- **`OE_REMASTERED`**:
  - `1`: Forces Remastered mode (point lights, ray shadows, contact ambient occlusion).
  - `0`: Forces Classic mode (authentic BREW software palette rasterization).
  - _Note:_ Overrides the persistent `LightingCfg` on startup without saving over it.

### Test Automation & Headless Harness (`main.c`)

- **`OE_PIPE`**:
  - Set to `1` to enable lock-step stdin/stdout text control.
  - Before every tick, the executable prints a status line (`S <tick> st <state> map <id> x <tx> y <ty> ...`) and reads a command line from stdin (`up`, `down`, `left`, `right`, `select`, `back`, `tp <x> <y> [ang]`, `shot <path.ppm>`, `quit`).
  - Automatically activates `OE_VCLOCK`.
- **`OE_VCLOCK`**:
  - Set to `1` to enable virtual clock execution (advances fixed tick time without sleeping, running as fast as CPU permits).
- **`OE_TICKS`**:
  - Caps total simulation ticks before exiting cleanly (e.g. `OE_TICKS=500`).
- **`OE_SEED`**:
  - Integer value providing a deterministic seed to the engine's random number generator (`GETRAND`).
- **`OE_KEYLOG`**:
  - Set to `1` to print all key events, state transitions, and actions to stdout.
- **`OE_KEYS`**:
  - Scripted keypress schedule formatted as `tick:key,tick:key,...` (e.g. `10:select,25:up,40:attack`).
- **`OE_SHOT`**:
  - Destination folder path to save PPM screenshots at exit and during scheduled ticks.
- **`OE_SHOT_AT`**:
  - Comma-separated list of tick numbers at which to capture screenshot PPMs into the directory specified by `OE_SHOT`.
