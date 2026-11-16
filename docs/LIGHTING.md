# Dynamic Lighting & Remastered Presentation

This document details the architecture, mathematics, light selection algorithms, geometric ray-tracing, ambient occlusion, sprite lighting models, and performance optimizations implemented in `src/host/lighting.c`.

## 1. System Overview

The dynamic lighting engine is a screen-space / world-space hybrid. Rather than modifying the fixed-point software rasterizer, the rasterizer logs geometric metadata during span and column passes into a `Surface` buffer. The lighting system then performs ray-traced geometric shading, dynamic light evaluation, and tone mapping directly onto the output pixels.

```
Rasterizer Passes (render.c, render_span.c, render_sprite.c)
   │
   ├── BrewLight_floor()   ──> Writes Floor / Ceiling Surfaces (kind = 1)
   ├── BrewLight_span()    ──> Writes Wall Surfaces (kind = 2) or Sprites (kind = 3)
   └── BrewLight_weapon()  ──> Writes Weapon Overlay Surfaces (kind = 4)
                                    │
                                    ▼
                          Surface Buffer [W × H]
                                    │
                                    ▼
       BrewLight_render() / samplePointQ10() / incidentEnergy()
   ┌─────────────────────────────────────────────────────────────┐
   │ 1. Light Candidate Gathering & View-Frustum Scoring         │
   │ 2. Geometric Line-Casting Shadow Rays (visibilityAt)        │
   │ 3. Ambient Occlusion & Contact Shading (contactShade)       │
   │ 4. Half-Lambert Diffuse Wrap Shading for Billboards         │
   │ 5. Quadratic Distance Attenuation & Torch Flicker           │
   │ 6. Tone Mapping & Color Space LUTs (byteToLinear, toneLUT)  │
   └─────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                         Lit Framebuffer [W × H]
```

## 2. Surface Buffer & Receiver Geometry

Each pixel on screen stores geometric metadata in a `Surface` structure:

```c
typedef struct {
  float x, y, z;          // World space coordinate (units: 64 = 1 tile)
  signed char nx, ny, nz; // Normal vector components scaled to [-127, 127]
  unsigned char kind;     // Surface classification
} Surface;
```

### Surface Classifications (`kind`)

- **`0`**: Unlit / Background / Sky (no lighting applied).
- **`1`**: Floor or Ceiling plane (`nz = +127` for floor, `-127` for ceiling).
- **`2`**: Architectural Wall plane (normal calculated from the BSP line segment).
- **`3`**: Billboard Quad Sprite (monsters, NPCs, items, decorations; normal faces the camera: `nx = -fx, ny = -fy`).
- **`4`**: Player Weapon overlay (illuminated in weapon space, ignores world distance fog).
- **`5`**: Special floor/ceiling variants.

## 3. Light Source Selection & Prioritization

### 3.1. Emitter Registration (`sources[]`)

Static props and active sprites register light properties in `sources[]`:

```c
typedef struct {
  int tile;               // Sprite / tile ID
  float r, g, b;          // Color channels (0.0 .. 1.0)
  float radius;           // Falloff radius in world units
  float power;            // Intensity multiplier
  float height;           // Vertical Z offset from sprite base
  int flicker;            // 1 = animated torch/fire flicker, 0 = constant
} Source;
```

#### Emitter Tables by Game Edition:

- **Orcs & Elves (`GAME_OE1`):**
  - **Wall Torches & Sconces:** Tile `116` (r=1.0, g=0.42, b=0.10, radius 230), `136` (Torchiere, radius 190, power 1.8), `181` (Wall sconce, radius 150), `185` (Fire sconce, radius 180).
  - **Fires & Braziers:** Tile `130` (Fire, radius 240), `145` (Fire Portal, r=0.80, g=0.35, b=1.0, radius 180, power 2.4, constant glow).
  - **Healing Crystals (Gaya's Hub / Caverns):** Tile `165` (r=0.15, g=0.50, b=1.0, radius 240, power 2.2).
  - **Dwarven Ghosts & King Brahm:** Tiles `65..67`, `69` (spectral cyan/blue spirit glow: r=0.30, g=0.70, b=1.0, radius 180, power 1.4..1.5).
  - **War Hammer World Pickup:** Tile `14` (legendary golden radiance: r=1.0, g=0.78, b=0.18, radius 170, power 1.6).
  - **Magic Seal Barrier:** Tile `137` (Entity #139, swirling golden/amber flame barrier: r=1.0, g=0.58, b=0.18, radius 190, power 1.8, flickering).
  - **Elemental Flames & Gems:** Tiles `220..223` (colored gems/crystals), `224`/`225` (blue/cyan magic flame), `227` (torch glow), `230` (fire column), `235` (purple fire), `238` (brazier flame), `242..245` (tinted glows), `252` (portal gate glow).

- **Orcs & Elves II (`OE2`):**
  - **Wall Sconces & Torches:** Tile `116`, `136`, `143` (Campaign torch, radius 210), `145`, `149`, `150` (Wall sconce, radius 210), `181` (Wall sconce, radius 150), `234`.
  - **Fires & Barriers:** Tile `130` (Fire, radius 240), `138` (Fire Portal Brazier, radius 240), `161` (Flame barrier, radius 220).
  - **Crystals & Gems:** Tile `14..16` (colored gems), `162`/`165` (Healing crystals), `224..238` (magic fire variants).

#### Player & Held Weapon Lights:

- **Inherent Player Ambient Light:** Always active:
  - **OE1:** Enhanced visibility for dark subterranean corridors (`radius = 160 * 1.2`, `power = 0.62`, `r=1.0, g=0.62, b=0.28`).
  - **OE2:** Original low-intensity ambient (`radius = 105 * 1.2`, `power = 0.28`, `r=1.0, g=0.62, b=0.28`).
- **Orcs & Elves (`oe1`) Weapons:**
  - `w == 2` (Flaming Sword), `w == 5` (Heavy Crossbow), `w == 7` (Phoenix Eggs): full firelight (`radius = 210`, `power = 1.15`, `r=1.0, g=0.38, b=0.08`).
  - `w == 3` (Vorpal Sword): enchanted blue light (`radius = 210`, `power = 1.15`, `r=0.25, g=0.55, b=1.0`).
  - Emissive weapons (`w in {0, 2, 3, 7, 8, 9, 10}`) receive a 1.4x self-illumination boost with a 1.25 minimum brightness floor.
- **Orcs & Elves II (`oe2`) Weapons:**
  - `w == 5` (Fire Crossbow), `w == 6` (Kinetic Crossbow), `w == 7` (Flaming Sword): full firelight (`radius = 210 * 1.2`, `power = 1.15`, `r=1.0, g=0.38, b=0.08`).
  - Wand Orbs (`w in {8..10}`): 75% intensity (`radius = 210 * 1.2`, `power = 0.86`):
    - Shrink Orb (`w == 8`): Red light (`r=1.0, g=0.18, b=0.10`).
    - Mold Orb (`w == 9`): Green light (`r=0.25, g=1.0, b=0.35`).
    - Freeze Orb (`w == 10`): Ice blue light (`r=0.35, g=0.65, b=1.0`).
  - Emissive weapons (`w in {0, 5, 6, 7, 8, 9, 10}`) receive a 1.4x self-illumination boost with a 1.25 minimum brightness floor.

### 3.2. View-Frustum Scoring (`selectionScore`)

Because a map may contain dozens of light sources, the top 7 world lights must be chosen based on visual impact.

```c
static float selectionScore(int key, float lx, float ly, float distanceSquared) {
  float dx = lx - processingX, dy = ly - processingY;
  float forward = dx * fx + dy * fy;
  float dist = sqrtf(distanceSquared);
  float cosA = dist > .01f ? forward / dist : 1.f;
  float dirWeight;

  if (forward >= 0.f) {
    // Forward view cone: strong priority boost (up to 4x better score)
    dirWeight = 1.f - 0.75f * fmaxf(0.f, cosA);
  } else {
    // Behind camera: heavily penalized (up to 10x penalty)
    dirWeight = 1.f + 4.f * (-forward / (WALK_STEP * 2.f));
    if (dirWeight > 10.f) dirWeight = 10.f;
  }

  float score = dist * dirWeight;
  // Hysteresis: retain previously active lights to avoid frame-to-frame flicker
  for (int i = 0; i < retainedCount; i++) {
    if (retainedKeys[i] == key) return score * 0.60f;
  }
  return score;
}
```

## 4. Ray-Traced Geometric Shadows

Shadows are computed via geometric line intersection against the BSP world lines (`Render.lines`):

- **Shadow Grid (`visibilityAt`):** The world is partitioned into a 16-unit grid. Ray segments from each grid sample point `(x, y, z)` toward the light source `(lx, ly, lz)` are tested against non-transparent BSP walls (`lineOccludes`).
- **Self-Shadow Avoidance:** The receiver surface position is nudged along its surface normal by 2 world units:
  ```c
  float x = (sx + s->nx / 127.f * 2.f) / 16.f;
  float y = (sy + s->ny / 127.f * 2.f) / 16.f;
  ```
- **Performance Optimization (`OE_NO_SPRITE_SHADOWS`):**
  On PS Vita and PC, `OE_NO_SPRITE_SHADOWS` is enabled. Sprites do not cast volumetric shadows onto the shadow grid, removing expensive per-frame sprite occluder rebuilds while preserving 100% of wall, column, and door shadows.

## 5. Shading Models & Critical Pitfalls

### 5.1. Half-Lambert Wrap Shading for Billboard Sprites

- **Problem:** Billboard sprites have a planar normal facing the camera (`nx = -fx, ny = -fy`). Under standard Lambertian diffuse shading (`N · L`), as soon as the player walks past a torch or the torch is slightly to the side/rear, `N · L <= 0`, causing the character sprite to abruptly turn completely black.
- **Solution:** Apply Half-Lambert diffuse wrap to billboard sprites (`kind == 3`):
  ```c
  float ndotl = (s->nx * dx + s->ny * dy + snz * dz) / (127.f * d);
  float lambert = (kind == 3) ? clampf(ndotl * 0.5f + 0.5f, 0.f, 1.f)
                              : clampf(ndotl, 0.f, 1.f);
  ```
  This creates smooth, three-dimensional wrap-around lighting on 2D monster and NPC sprites.

### 5.2. Floor Contact Shading Pitfall on Billboards

- **Problem:** `contactShade()` computes ambient occlusion near wall-floor corners using distance to floor:
  `distance = fabsf(sz - renderer->floorZ);`
  For standing character billboards, the bottom pixels are at floor height (`distance ≈ 0`), which caused `contactShade` to evaluate to `0.35` (a **65% penalty** on ambient and direct lighting). This made characters standing on the ground look artificially crushed and dark.
- **Solution:** Billboard sprites must be exempted from floor crease AO:
  ```c
  int kind = surfKind(s);
  if (kind == 4 || kind == 3) return 1.0f;
  ```

### 5.3. Distance Culling Pitfall (`processingSteps` & `worldLightWeight`)

- **Problem:** `processingSteps` was originally initialized to `5` (5 tiles = 320 units).
  - In `lightInRegion`, lights further than `reach = 5 * 64 + radius` (around 500 units) from the player were completely discarded from selection.
  - In `incidentEnergy()`, `worldLightWeight(sx, sy)` computed distance from the _player_ to the surface. Beyond 5 tiles, it returned `0.0`.
  - When standing across a large cavern (e.g. Dragon Lair, 10–14 tiles away), Gaya and distant cavern walls received **zero dynamic light**, even when standing right next to a burning brazier!
- **Solution:**
  1. Set `processingSteps = 26` by default (covering up to 1664 world units).
  2. Allow `BrewLight_setRange` up to `32` steps (2048 units).
  3. Exempt sprites (`kind == 3`) from player distance culling:
     ```c
     float weight = (kind == 3 || kind == 4) ? 1.0f : worldLightWeight(sx, sy);
     if (weight <= 0.0f) return;
     ```

### 5.4. Distance Haze Red-Channel Crushing

- **Problem:** `samplePointQ10()` blends energy with a dark mist haze (`0.035, 0.065, 0.105`). At depths > 128 units, multiplying by `(1 - haze)` stripped warm red tones from distant sprites, turning Gaya into a dark silhouette.
- **Solution:** Restrict haze color crushing to non-sprite environmental geometry:
  ```c
  if (kind != 4 && kind != 3 && fadeLevel > 0) { ... }
  ```

## 6. Color Space & Tone Mapping

Lighting values are evaluated in linear radiometric units and mapped to display gamma through precomputed lookup tables:

- **`byteToLinear[256]`**: Converts sRGB color bytes `v` to linear intensity: `(v / 255)^2`.
- **`byteToLinearQ10[256]`**: 10-bit fixed-point linear representation (`* 1024.f`) for fast integer SIMD/multi-core shading.
- **`toneLUT[4096]`**: Reinhard-style soft shoulder curve:
  ```c
  float lin = i * (4.f / 4096.f);
  float mapped = lin > 1.f ? lin / (1.f + (lin - 1.f) * 0.7f) : lin;
  toneLUT[i] = (uint8_t)(clampf(sqrtf(mapped), 0.f, 1.f) * 255.f + 0.5f);
  ```
  Prevents blown-out color banding when multiple lights overlap while preserving bright specular highlights.

## 7. Performance Optimizations (PS Vita & PC)

1. **Multi-threaded Slicing:** Column spans are sliced across a 4-thread worker pool (`LightWorkerCtx`).
2. **Q10 Fixed-Point Interpolation:** `samplePointQ10` processes low-resolution irradiance grids and bilinearly interpolates across wall spans using integer arithmetic.
3. **Atomic Cache Flags:** `wallCheckedAtomic` avoids redundant ray-casts across thread boundaries using lock-free acquire/release semantics.
4. **Frame Skip & Lighting Bypass (`BrewLight_setSkip`):** When presentation is locked or no world simulation/camera change occurs, full-frame lighting recalculations and framebuffer reconstruction are bypassed.
5. **Normal-Offset Coordinate Precalculation (`ShadowSampleCoord`):** The 2-unit normal offset (`initShadowCoord`) is computed once per surface/column rather than re-evaluating normal geometry inside inner line-occlusion ray loops.
6. **Integer Span Stepping:** Span rendering caches `cachedSpanZBase16` and `cachedSpanDz16` (16.16 fixed-point) to eliminate per-pixel floating-point divisions during raster span traversal.
7. **Precalculated Falloff & Attenuation Tables:**
   - Active world lights precalculate `lightRadius2[8]`, `lightEffR2[8]`, `lightInvRadius[8]`, and `lightGain[8]` once per frame, turning inner falloff calculations into simple multiply-adds.
   - `FLOOR_SHADOW_SLOTS` (16) and `ROOM_DIST_SLOTS` (16) cached lookup tables accelerate floor shadow tests.
8. **Discontinuity-Aware Bilateral Surface Compatibility (`compatibleSurfaceMax`):** Preserves geometric, depth, and normal edges during coarse irradiance grid reconstruction, preventing light bleeding across corners and wall silhouettes.

## 8. Multi-Game Considerations & Known Visual Trade-offs


### 8.1. High Emitter Density & Static Lighting Optimization in Gaya's Hub (OE1 Map 9)

  In Orcs & Elves I (`Map 9: Dragon's Lair` / Gaya's hub, `MAP_GAYA = 6008`), the map contains an exceptionally high concentration of dynamic light emitters in a single cavern:
- **10 Healing Crystals** (Tile `165`).
- **8 Fire Portals** (Tile `145`).
- **8 Torchieres / Wall Sconces** (Tiles `116`, `136`, `185`).
- **Gaya Dragon Body & Head** (Tiles `20` and `191`).

  Previously, this density severely degraded frame rate on low-power devices like the PS Vita because:

1. Candidate emitters thrash the active 7-light budget on camera rotations, dirtying shadow caster tables and wall visibility caches.
2. Animated sprites (Gaya breathing, swirling portals, crystal shimmer) continually alter unlit framebuffer hashes (`sig`), completely defeating stationary frame reuse caches.
3. Torches and portals had active flicker enabled (`flicker = 1`), preventing static light clustering and forcing continuous recalculation.

#### Static Lighting Architecture in Gaya's Hub

Because Gaya's Hub is a peaceful location with no weapon swinging or combat and static geometry:

1. **Selective Static Emitter Consolidation (`gayaHubActive`):**
   - The 10 Healing Crystals placed atop each other in the central fountain are merged into 1 unified crystal cluster (`mergeR = 200`, `radius = 280`, `power = 2.4`).
   - Gaya dragon's head and body are merged into 1 central dragon flame cluster (`mergeR = 350`, `radius = 380`, `power = 2.8`).
   - The 8 Fire Portals (tile `145`) and wall torchieres retain their own independent emitters centered directly at each sprite's 3D coordinates with generous falloff (`radius = 220`, `power = 2.4`) and non-flickering static emission (`flicker = 0`), ensuring every portal and torch casts its own vibrant glow onto adjacent walls.
2. **Occluder-Free Direct Ambient Shading:**
   - Map 9's cavern is an open chamber without interior occluding partitions.
   - For `gayaHubActive`, ray-marching line-of-sight tests (`shadowCoordCtx`) are bypassed in favor of direct distance attenuation and contact ambient occlusion (`e *= shadowScale`).
   - Eliminates trace grid ray traversal completely, sustaining 60 FPS while keeping clean bilinear per-pixel span interpolation across all rows and columns.
