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

Each pixel on screen stores geometric metadata in a compact 8-byte `Surface` structure (sized so `352×166` fits inside the PS Vita's 512 KB L2 cache):

```c
typedef struct {
  int16_t x, y, zKind; // Q2 fixed-point (1/4 world unit); z in bits 3..15, rawKind in bits 0..2
  signed char nx, ny;  // Horizontal normal components scaled to [-127, 127]
} Surface;
```

### Surface Classifications (`rawKind` / `surfKind`)

- **`0`**: Unlit / Background / Sky (no lighting applied).
- **`1`**: Floor plane (`nz = +127`, `surfKind = 1`).
- **`2`**: Architectural Wall plane (normal calculated from the BSP line segment).
- **`3`**: Billboard Quad Sprite (monsters, NPCs, items, decorations; normal faces the camera: `nx = -fx, ny = -fy`).
- **`4`**: Player Weapon overlay (illuminated in weapon space, ignores world distance fog).
- **`5`**: Ceiling plane (`nz = -127`, `surfKind` maps `5` to `1`).

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
  - **Crystals & Gems:** Tiles `14..16` (colored gems), `220..223` (colored crystals), `224..238` (magic fire variants), `242..245`, `252`.

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

Because a map may contain dozens of light sources, the top 7 world lights must be chosen based on visual impact (plus slot 8 reserved for the player's held/ambient light, key `2000`, and up to 8 timed projectile `Impact` lights).

```c
static float selectionScore(int key, float lx, float ly, float distanceSquared,
                            float radius, float power) {
  float dx = lx - processingX, dy = ly - processingY;
  float forward = dx * fx + dy * fy;
  float dist = sqrtf(distanceSquared);
  float cosA = dist > .01f ? forward / dist : 1.f;
  float dirWeight;

  if (forward >= 0.f) {
    // Forward view cone: priority boost
    dirWeight = 1.f - 0.65f * fmaxf(0.f, cosA);
  } else {
    // Behind camera: penalized relative to influence radius (up to 10x)
    float behindNorm = (-forward) / fmaxf(radius, WALK_STEP * 2.f);
    dirWeight = 1.f + 4.f * behindNorm * behindNorm;
    if (dirWeight > 10.f) dirWeight = 10.f;
  }

  float strength = fmaxf(0.5f, (radius / 240.f) * sqrtf(fmaxf(power, 0.25f)));
  if (strength > 2.5f) strength = 2.5f;
  float score = (dist * dirWeight) / strength;
  // Hysteresis: retain previously active lights to avoid frame-to-frame flicker
  for (int i = 0; i < retainedCount; i++) {
    if (retainedKeys[i] == key) return score * .60f;
  }
  return score;
}
```

## 4. Ray-Traced Geometric Shadows

Shadows are computed via geometric line intersection against the BSP world lines (`Render.lines`), accelerated by a 64×64×64-unit 2D DDA trace grid (`buildTraceGrid()`, `TraceLineGeom`):

- **Shadow Grid (`visibilityAt`):** The world is partitioned into a `128×128×24` grid (16×16×8 world units per cell) stored in `wallVisState[]` (2 atomic bits per light slot `0..7`). Ray segments from each grid sample point `(x, y, z)` toward the light source `(lx, ly, lz)` traverse the DDA grid via `BrewLight_visible()` and test non-transparent walls with `lineGeomOccludes()`.
- **Z-Bounds Fast Path:** `lineGeomOccludes()` rejects rays whose `[zMin, zMax]` interval does not overlap `[zBottom, zTop]`, and skips the `nt / den` division whenever both ray endpoints are already inside the wall's vertical span.
- **Self-Shadow Avoidance:** The receiver surface position is nudged along its surface normal by 2 world units:
  ```c
  float x = (sx + s->nx * (2.f / 127.f)) * (1.f / 16.f);
  float y = (sy + s->ny * (2.f / 127.f)) * (1.f / 16.f);
  ```
- **Performance Optimization (`OE_NO_SPRITE_SHADOWS`):**
  On PS Vita and PC, `OE_NO_SPRITE_SHADOWS` is enabled. Sprites do not cast volumetric shadows onto the shadow grid, removing expensive per-frame sprite occluder rebuilds while preserving 100% of wall, column, and door shadows.

## 5. Shading Models & Critical Pitfalls

### 5.1. Half-Lambert Wrap Shading for Billboard Sprites

- **Problem:** Billboard sprites have a planar normal facing the camera (`nx = -fx, ny = -fy`). Under standard Lambertian diffuse shading (`N · L`), as soon as the player walks past a torch or the torch is slightly to the side/rear, `N · L <= 0`, causing the character sprite to abruptly turn completely black.
- **Solution:** Apply Half-Lambert diffuse wrap to billboard sprites (`kind == 3`):
  ```c
  float invD127 = (1.f / 127.f) / (d + .01f);
  float ndotl = dot * invD127;
  float lambert = (kind == 3) ? clampf(ndotl * .35f + .65f, 0.f, 1.f)
                              : clampf(ndotl, 0.f, 1.f);
  ```
  This creates smooth, three-dimensional wrap-around lighting on 2D monster and NPC sprites.

### 5.2. Floor Contact Shading Pitfall on Billboards

- **Problem:** `contactShadeCtx()` computes ambient occlusion near wall-floor corners using distance to floor and walls. For standing character billboards, the bottom pixels are at floor height (`distance ≈ 0`), which caused `contactShade` to evaluate to `0.35` (a **65% penalty** on ambient and direct lighting). This made characters standing on the ground look artificially crushed and dark.
- **Solution:** Billboard sprites (`kind == 3`) and weapons (`kind == 4`) are exempted from floor/wall crease AO (`return 1.f;`).

### 5.3. Distance Culling Pitfall (`processingSteps` & `worldLightWeight`)

- **Problem:** `processingSteps` was originally initialized to `5` (5 tiles = 320 units).
  - In `lightInRegion`, lights further than `reach = 5 * 64 + radius` from the player were completely discarded from selection.
  - In `incidentEnergyCtx()`, `worldLightWeight(sx, sy)` computed distance from the _player_ to the surface. Beyond 5 tiles, it returned `0.0`.
  - When standing across a large cavern (e.g. Dragon's Lair), distant cavern walls and NPCs received **zero dynamic light**, even when standing right next to a burning brazier!
- **Solution:**
  1. `BrewLight_setRange(steps)` allows `5..20` steps (`standalone_bridge.c` sets `rangeSteps = 14` for OE1 and `20` for OE2).
  2. Exempt sprites (`kind == 3`) and weapons (`kind == 4`) from player distance culling:
     ```c
     float weight = (kind == 3 || kind == 4) ? 1.f : worldLightWeight(sx, sy);
     if (weight <= 0) return;
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
- **`byteToLinearQ10[256]`**: 10-bit fixed-point linear representation (`* 1024.f`) for fast integer shading.
- **`toneLUT[4097]`**: Soft-shoulder curve over `[0.0 .. 4.0]`:
  ```c
  float lin = i * (4.f / 4096.f);
  float mapped = lin > 0.75f
                     ? 0.75f + 0.25f * (lin - 0.75f) / ((lin - 0.75f) + 0.8f)
                     : lin;
  toneLUT[i] = (uint8_t)(clampf(sqrtf(mapped), 0.f, 1.f) * 255.f + .5f);
  ```
  Prevents blown-out color banding when multiple lights overlap while preserving bright highlights.
- **`expLUT[257]` & `sqrtLUT[4097]`**: Accelerates screen-space light halos in `glow()` without per-pixel `expf()` or `sqrtf()` calls.

## 7. Performance Optimizations (PS Vita & PC)

1. **Multi-threaded Slicing (`OE_LIGHT_MT`):** On PS Vita, `LIGHT_THREADS = 3` (main thread + 2 worker threads pinned to `SCE_KERNEL_CPU_MASK_USER_0..2`) processes 32-column chunks in parallel via `sceKernelSignalSema` / `sceKernelWaitSema`.
2. **Thread-Local Worker Caches (`LightWorkerCtx`):** `floorShadowCache[8][64]`, `roomDistCache[64]`, `shadowColumns[COL_CACHE_SLOTS][8]`, and `cornerCache[COL_CACHE_SLOTS]` (`64` slots per worker on Vita, `1024` on single-threaded builds) live inside each worker's context to eliminate cross-core false sharing.
3. **Q10 Fixed-Point Coarse Grid (`coarseGrid`):** Phase 0 evaluates `samplePointQ10()` on an `8×2` (`w > 176`) or `4×2` grid (fusing the `y - 2` vertical midpoint fill into the `y += 4` pass); Phase 1 bilinearly interpolates across compatible spans using integer arithmetic.
4. **Early Culling & Division Avoidance:** Precalculated `lightRadius2[8]`, `lightEffR2[8]`, `lightBackfaceR2[8]`, `lightInvRadius[8]`, and `lightGain[8]` cull out-of-range and back-facing lights before `sqrtf(d2)` and skip the normal-dot division when `dot <= 0`.
5. **Atomic Cache Flags:** `wallCheckedAtomic` and `wallVisState` avoid redundant ray-casts and distance-field queries across threads using lock-free atomics.
6. **Per-Span Weapon Capture & Stationary Caching:** `BrewLight_weapon()` saves background surfaces and framebuffer pixels only for the weapon's own spans when `weaponCanShift()` is active; `standalone_bridge.c` caches stationary poses (`samePose`) to skip lighting when the unlit framebuffer hash and camera pose match.
7. **Span & Emitter Caching:** `BrewLight_span()` caches `projection` and line-normal invariants across adjacent columns; `gather()` caches static emitter sprite indices (`emitterSprites[]`) per map.
8. **Discontinuity-Aware Bilateral Surface Compatibility (`compatibleSurfaceMax`):** Preserves geometric, depth, and normal edges during coarse irradiance grid reconstruction, preventing light bleeding across corners and wall silhouettes.

## 8. Multi-Game Considerations & Known Visual Trade-offs

### 8.1. High Emitter Density & Static Lighting Optimization in Dragon's Lair (OE1 Map 6008)

In Orcs & Elves I (`Map 9: Dragon's Lair` / Gaya's hub, `6008`), the open cavern contains **233 sprites** (including 77 ceiling stalactites, 27 gold hoard mounds, 10 healing crystals `165`, 8 fire portals `145`, 8 torchieres `136`, and Gaya `185` drawn as 8 overlapping layers):

1. **Static Emitter Consolidation (`gayaHubActive`):**
   - The 10 Healing Crystals (`165`) merge into 1 central cluster (`mergeR = 200`, `radius = 280`, `power = 2.4`).
   - Gaya's emitter (`185` / `20` / `191`) merges into 1 central dragon cluster (`mergeR = 350`, `radius = 380`, `power = 2.8`).
   - The 8 Fire Portals (`145`) and wall torchieres retain independent static emitters (`flicker = 0`, portal `radius = 220`).
   - `emitterSprites[]` caches emitter sprite indices per map so `gather()` only inspects emitter sprites rather than all 233 sprites.
2. **Occluder-Free Shading & Analytical AO:**
   - Ray-marching line-of-sight tests (`shadowCoordCtx`) are bypassed in favor of direct distance attenuation and contact shade (`e *= shadowScale`).
   - `contactShadeCtx()` uses analytical vertical floor/ceiling crease distance instead of querying the 2D `wallDistanceAt` field.
3. **Coarse Grid Interpolation Across Cavern Props:**
   - Because `gayaHubActive` has no sharp shadow boundaries, `compatibleSpan()` and `compatibleSurfaceMax()` interpolate across adjacent stalactites, gold mounds, and Gaya's sprite layers instead of falling back to per-pixel `samplePointQ10()` on every sprite edge.
4. **Stationary Partial Relight (`prevHubOriginal[]`):**
   - When the camera pose is unchanged while staggered 2D sprite animations (portals, crystals, Gaya's wiggle) invalidate `lastFrameSig`, `present()` skips `gather()` and Phase 0/1 and re-shades only the pixels where `original[i] != prevHubOriginal[i]` from the cached `coarseGrid`.
5. **Catch-Up Rasterization Skip & Horizon Clamp:**
   - When `OE_shouldSkipPresent()` is set on intermediate 15 ms catch-up ticks in `main_vita.c`, `Render_render` updates camera/floor/drunk state and skips 3D pixel rasterization so simulation runs at full 66.7 Hz speed without redundant software renders, and `Render_drawFloorCeiling` clamps `halfH` to the viewport bottom when `gayaPitch` tilts the camera upward.
