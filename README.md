# Orcs & Elves I & II (PlayStation Vita)

![Orcs & Elves](screenshot.png)

A modern port of the classic id Software dungeon crawlers Orcs & Elves and Orcs & Elves II — now featuring remastered lighting, widescreen support, and refined controls!

## Features

- **Remastered lighting:** Adds real-time point lighting, geometric ray shadows, contact ambient occlusion, and projectile impact flashes while keeping all original BREW textures and sprites, switchable in Options with Classic mode.
- **Widescreen support:** Renders at `352×200` widescreen (instead of the original `176×220` phone layout) scaled to the PS Vita's `960×544` native resolution.
- **Faithful simulation:** Preserves the original BREW gameplay timing and RNG.
- **Fully tested:** Completely playable and tested from start to finish on real PlayStation Vita hardware.

## Installation

### Orcs & Elves

- Obtain official [game files](https://archive.org/details/oe1_brew), and copy them to `ux0:data/oe1/` on your Vita.
- Download the [latest release](https://github.com/sweetpalma/orcs-and-elves-vita/releases).
- Install `oe1.vpk` on your Vita.
- Enjoy!

### Orcs & Elves II

- Obtain official [game files](https://archive.org/details/oe2_brew), and copy them to `ux0:data/oe2/` on your Vita.
- Download the [latest release](https://github.com/sweetpalma/oe-2-vita/releases).
- Install `oe2.vpk` on your Vita.
- Enjoy!

## Controls

- **Movement & Turning:**
  - **D-Pad:** Movement and menu navigation.
  - **Triggers:** Strafing.
- **Actions & Combat:**
  - **Cross (`X`):** Attack or interact.
  - **Triangle (`△`):** Cycle weapons or skip dialogues.
  - **Square (`□`):** Skip turn.
  - **Circle (`○`):** Cancel.
- **System:**
  - **Start:** Pause.
  - **Select:** Map.

## Development

Pull requests and bug reports are highly encouraged! Feel free to open an issue or submit a PR if you run into any problems or want to contribute improvements.

### Docker Build

```sh
# Build PS Vita .vpk
docker compose run --rm --build vita

# Build PC binary
docker compose run --rm --build pc
```

### Native Build

To build the standard PS Vita package (requires VitaSDK at `tools/vendor/vitasdk` or `VITASDK` environment variable):

```sh
python3 tools/build_vita.py
```

To build for PC locally (requires CMake and SDL2):

```sh
python3 tools/build_pc.py
```

You can also pass `--bundle-data` to bundle game data directly inside the `.vpk` (requires the files in `data/`). This is intended **strictly for local debug and testing purposes**, not for distribution.

```sh
python3 tools/build_vita.py --bundle-data
```

## License

This project is distributed under the GNU General Public License v3.0. See [LICENSE](LICENSE) for the full license text, and [SOURCES.md](SOURCES.md) for upstream provenance and author credits.

Original game assets are the property of id Software and Fountainhead Entertainment and are not included in this repository.
