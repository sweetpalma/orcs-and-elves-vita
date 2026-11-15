# Orcs & Elves II - Technical Documentation

This directory contains technical documentation, system architecture references, and findings gathered during the development, reverse-engineering, dynamic lighting implementation, and overall porting efforts.

## Documentation Index

- `ARCHITECTURE.md`:
  Comprehensive codebase architecture: simulation loop (40 ms / 25 Hz), engine state machines, canvas & BSP rendering, asset pipeline (`.bar`, `.mod`), host bridge, and PS Vita platform adapter.

- `LIGHTING.md`:
  In-depth guide to the remastered dynamic lighting system (`src/host/lighting.c`): candidate selection, view-frustum scoring, geometric ray shadows, ambient occlusion, billboard sprite shading, distance culling pitfalls, and Vita-specific performance optimizations.

- `ENVIRONMENT.md`:
  Complete reference for all build variables, compile-time flags, CLI options, and runtime environment variables (`OE_DATA_DIR`, `OE_PIPE`, `OE_REMASTERED`, `OE_STANDALONE_BRIDGE`, etc.).

- `TESTING.md`:
  Automated testing guide and reference for `tools/oe2test.py` and the `OE_PIPE` headless harness: automated smoke tests, telemetry parsing, deterministic world hashing, CLI usage, and Python API examples.

- `RESOURCES.md`:
  Reverse-engineered binary formats and resource layout for Qualcomm BREW 7.x (`orcsandelves2.bar`): entity records, weapon definitions, string tables, 32x32 map BSP formats, graphics mappings, bitshapes, texels, and palettes.
