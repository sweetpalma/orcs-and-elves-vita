#!/usr/bin/env python3
"""
OEData - Comprehensive Data Inspection Tool for Orcs & Elves / Orcs & Elves II (.bar archives)
Standard library only (Python 3.8+).

Parses:
  - BREW .bar resource archives (Resource types, gzip payload decompression)
  - strings.bin (Grouped string tables with hyphens/formatting markers, OE2)
  - entities.bin (Entity definitions: tileIndex, subId, eType, eSubType, parm, names/descriptions)
  - mappings.bin (Wall, Flat, Sprite mappings and Remap tables)
  - palettes.bin (RGB565 palettes converted to RGB888)
  - bitshapes.bin (Sprite dimensions, bounding boxes, stexels index)
  - Map BSPs (OE1: 6000..6011; OE2: 2000..2013: header, nodes, lines, sprites,
    tile grids, events, bytecodes, ASCII visualization)
"""

from __future__ import annotations

import argparse
import gzip
import os
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class GameConfig:
    game_id: str  # "oe1" or "oe2"
    title: str
    bar_default: str
    res_entities: int
    res_sintable: int
    res_palettes: int
    res_bitshapes: int
    res_mappings: int
    res_map_base: int  # map N is res_map_base + N
    res_strings: Optional[int]
    map_names: Dict[int, str]
    campaign_map_range: range
    candidate_emitters: Dict[int, str]


OE1_CONFIG = GameConfig(
    game_id="oe1",
    title="Orcs & Elves",
    bar_default="orcsandelves.bar",
    res_entities=5001,
    res_sintable=5002,
    res_palettes=5005,
    res_bitshapes=5006,
    res_mappings=5007,
    res_map_base=5999,  # map 1 = 6000
    res_strings=None,
    map_names={
        1: "Entrance Hall",
        2: "Prison",
        3: "Great Hall",
        4: "Labyrinth",
        5: "Catacombs",
        6: "Throne Room",
        7: "The Pit",
        8: "Twilight Cavern",
        9: "Dragon's Lair",
        10: "Orcs & Elves",
        11: "Items",
    },
    campaign_map_range=range(1, 10),  # 1..9 (through Dragon's Lair)
    candidate_emitters={
        116: "Wall Torch / Sconce",
        130: "Fire",
        136: "Torchiere",
        145: "Fire Portal",
        165: "Healing Crystal",
        181: "Wall Sconce",
        185: "Fire Sconce",
        220: "Red Crystal",
        221: "Green Crystal",
        222: "Blue Crystal",
        223: "Yellow Crystal",
        224: "Magic Flame (Blue)",
        225: "Magic Flame (Cyan)",
        227: "Torch Glow",
        230: "Fire Column",
        235: "Purple Fire",
        238: "Brazier Flame",
        242: "Orange Glow",
        243: "Blue Glow",
        245: "Green Glow",
        252: "Portal Gate Glow",
        280: "Fire Portal Door",
    },
)

OE2_CONFIG = GameConfig(
    game_id="oe2",
    title="Orcs & Elves II",
    bar_default="orcsandelves2.bar",
    res_entities=1000,
    res_sintable=1001,
    res_palettes=1003,
    res_bitshapes=1005,
    res_mappings=1004,
    res_map_base=1999,  # map 1 = 2000
    res_strings=1002,
    map_names={
        1: "Caverns",
        2: "Dwarkar",
        3: "Tunnels",
        4: "El'Landra",
        5: "Dark Forest",
        6: "Sol",
        7: "Darkfel",
        8: "Ben's Map",
        9: "Brett",
        10: "Items",
        11: "Jah",
        12: "Karina",
        13: "Matt",
        14: "Monster Map",
    },
    campaign_map_range=range(1, 8),  # 1..7 (Sol / Darkfel)
    candidate_emitters={
        130: "Fire",
        138: "Fire Portal Brazier (Sol / Darkfel)",
        143: "Torch / Sconce (Campaign)",
        145: "Fire Portal Brazier / Sconce",
        150: "Wall Sconce",
        161: "Flame Barrier (Sol / Darkfel)",
        181: "Wall Sconce",
    },
)

# Backward-compatibility alias
MAP_NAMES_BY_INDEX = OE2_CONFIG.map_names


def clean_text(text: str) -> str:
    """Clean game formatting characters (soft hyphens, bars)."""
    return text.replace("\xad", "").replace("-", "-").replace("|", " ").strip()


def normalize_for_search(text: str) -> str:
    """Normalize text for fuzzy search: lowercase, strip hyphens, spaces, punctuation."""
    return "".join(c for c in text.lower() if c.isalnum())


# -----------------------------------------------------------------------------
# BAR Archive
# -----------------------------------------------------------------------------
@dataclass
class BarEntry:
    id: int
    res_type: int
    offset: int
    size: int
    name: str = ""
    is_compressed: bool = False


class BarArchive:
    """Parser for Qualcomm BREW 7.x resource archive (.bar)."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"Archive not found: {self.path}")

        with open(self.path, "rb") as f:
            self.raw_data = f.read()

        self.entries: Dict[int, BarEntry] = {}
        self.name_to_id: Dict[str, int] = {}
        self._parse_header()

    def _parse_header(self) -> None:
        data = self.raw_data
        if len(data) < 0x20:
            raise ValueError("BAR file too small")

        ntypes = struct.unpack_from("<H", data, 6)[0]
        typedir = struct.unpack_from("<I", data, 8)[0]
        tbl = struct.unpack_from("<I", data, 16)[0]
        tblend = struct.unpack_from("<I", data, 24)[0]
        nent = (tblend - tbl) // 4

        for k in range(ntypes):
            t, first, span, idx = struct.unpack_from("<HHHH", data, typedir + k * 8)
            if t != 6:  # Type 6 = data resource
                continue
            for j in range(span + 1):
                if idx + j >= nent:
                    break
                o = struct.unpack_from("<I", data, tbl + 4 * (idx + j))[0]
                e = (
                    struct.unpack_from("<I", data, tbl + 4 * (idx + j + 1))[0]
                    if idx + j + 1 < nent
                    else len(data)
                )
                if o > len(data) - 2 or e > len(data) or e < o:
                    continue
                hl = struct.unpack_from("<H", data, o)[0]
                if hl < 2 or hl > e - o:
                    continue

                res_id = first + j
                payload_offset = o + hl
                payload_size = e - o - hl
                payload = data[payload_offset : payload_offset + payload_size]

                name = ""
                is_comp = len(payload) > 10 and payload[:2] == b"\x1f\x8b"
                if is_comp:
                    # Parse gzip FNAME if present
                    flags = payload[3]
                    p = 10
                    if flags & 4:  # FEXTRA
                        p += 2 + struct.unpack_from("<H", payload, p)[0]
                    if flags & 8 and p < len(payload):  # FNAME
                        end = payload.find(b"\x00", p)
                        if end != -1:
                            name = payload[p:end].decode("ascii", "replace")

                entry = BarEntry(
                    id=res_id,
                    res_type=t,
                    offset=payload_offset,
                    size=payload_size,
                    name=name,
                    is_compressed=is_comp,
                )
                self.entries[res_id] = entry
                if name:
                    self.name_to_id[name.lower()] = res_id
                    self.name_to_id[Path(name).stem.lower()] = res_id

    def detect_game(self) -> GameConfig:
        """Infer target game config from resource IDs and file path."""
        if OE1_CONFIG.res_entities in self.entries or OE1_CONFIG.res_palettes in self.entries:
            return OE1_CONFIG
        if OE2_CONFIG.res_entities in self.entries or OE2_CONFIG.res_palettes in self.entries:
            return OE2_CONFIG
        p_str = str(self.path).lower()
        if "orcsandelves2" in p_str:
            return OE2_CONFIG
        if "orcsandelves" in p_str:
            return OE1_CONFIG
        return OE2_CONFIG

    def get_raw(self, res_id_or_name: int | str) -> Optional[bytes]:
        res_id = self._resolve_id(res_id_or_name)
        if res_id is None or res_id not in self.entries:
            return None
        ent = self.entries[res_id]
        return self.raw_data[ent.offset : ent.offset + ent.size]

    def get(self, res_id_or_name: int | str) -> Optional[bytes]:
        """Get decompressed payload for a resource."""
        raw = self.get_raw(res_id_or_name)
        if raw is None:
            return None
        if len(raw) > 2 and raw[:2] == b"\x1f\x8b":
            try:
                return gzip.decompress(raw)
            except Exception:
                return raw
        return raw

    def _resolve_id(self, res_id_or_name: int | str) -> Optional[int]:
        if isinstance(res_id_or_name, int):
            return res_id_or_name
        s = str(res_id_or_name).strip().lower()
        if s.isdigit():
            return int(s)
        return self.name_to_id.get(s)


# -----------------------------------------------------------------------------
# Strings Table
# -----------------------------------------------------------------------------
class StringTable:
    """Parser for strings.bin (OE2: res 1002)."""

    def __init__(self, data: bytes):
        self.groups: List[List[str]] = []
        num_groups = struct.unpack_from("<I", data, 0)[0]
        offsets = struct.unpack_from(f"<{num_groups}I", data, 4)
        for g in range(num_groups):
            start = offsets[g]
            end = offsets[g + 1] if g + 1 < num_groups else len(data) - 4
            chunk = data[4 + start : 4 + end]
            parts = chunk.split(b"\x00")
            strs = [p.decode("latin1", "replace") for p in parts]
            self.groups.append(strs)

    def get(self, group: int, idx: int, clean: bool = False) -> str:
        if 0 <= group < len(self.groups) and 0 <= idx < len(self.groups[group]):
            val = self.groups[group][idx]
            return clean_text(val) if clean else val
        return ""

    def search(self, query: str) -> List[Tuple[int, int, str]]:
        q_norm = normalize_for_search(query)
        q_raw = query.lower()
        results = []
        for g_idx, grp in enumerate(self.groups):
            for s_idx, s in enumerate(grp):
                if q_raw in s.lower() or (
                    q_norm and q_norm in normalize_for_search(s)
                ):
                    results.append((g_idx, s_idx, s))
        return results


# -----------------------------------------------------------------------------
# Entity Definitions
# -----------------------------------------------------------------------------
@dataclass
class EntityDef:
    index: int
    tile_index: int
    sub_id: int
    etype: int
    esubtype: int
    parm: int
    name_id: int
    long_name_id: int
    desc_id: int
    name: str = ""
    long_name: str = ""
    description: str = ""


class EntityTable:
    """Parser for entities.bin (OE1: res 5001, OE2: res 1000)."""

    def __init__(
        self,
        data: bytes,
        strings: Optional[StringTable] = None,
        game_id: str = "oe2",
    ):
        self.defs: List[EntityDef] = []
        if len(data) < 2:
            return
        num_defs = struct.unpack_from("<H", data, 0)[0]

        is_fixed = (2 + num_defs * 13 == len(data)) and game_id != "oe1"
        if is_fixed:
            # OE2: Fixed 13-byte records referencing strings.bin
            for i in range(num_defs):
                off = 2 + i * 13
                (
                    tile,
                    sub_id,
                    etype,
                    esubtype,
                    parm,
                    name_id,
                    lname_id,
                    desc_id,
                ) = struct.unpack_from("<hBBBhHHH", data, off)

                name = strings.get(1, name_id, clean=False) if strings else ""
                lname = strings.get(1, lname_id, clean=False) if strings else ""
                desc = strings.get(1, desc_id, clean=False) if strings else ""

                ed = EntityDef(
                    index=i,
                    tile_index=tile,
                    sub_id=sub_id,
                    etype=etype,
                    esubtype=esubtype,
                    parm=parm,
                    name_id=name_id,
                    long_name_id=lname_id,
                    desc_id=desc_id,
                    name=name,
                    long_name=lname,
                    description=desc,
                )
                self.defs.append(ed)
        else:
            # OE1: Variable-length records with embedded names and descriptions
            pos = 2
            for i in range(num_defs):
                if pos + 4 > len(data):
                    break
                tile = struct.unpack_from("<h", data, pos)[0]
                icon = data[pos + 2]
                nlen = data[pos + 3]
                pos += 4
                name = (
                    data[pos : pos + nlen].decode("latin1", "replace")
                    if nlen > 0
                    else ""
                )
                pos += nlen

                lnlen = data[pos] if pos < len(data) else 0
                pos += 1
                lname = (
                    data[pos : pos + lnlen].decode("latin1", "replace")
                    if lnlen > 0
                    else name
                )
                pos += lnlen

                dend = data.find(b"\x00", pos)
                if dend != -1:
                    desc = data[pos:dend].decode("latin1", "replace")
                    pos = dend + 1
                else:
                    desc = ""
                    pos = len(data)

                etype = data[pos] if pos < len(data) else 0
                esubtype = data[pos + 1] if pos + 1 < len(data) else 0
                pos += 2
                parm = (
                    struct.unpack_from("<i", data, pos)[0]
                    if pos + 4 <= len(data)
                    else 0
                )
                pos += 4

                ed = EntityDef(
                    index=i,
                    tile_index=tile,
                    sub_id=icon,
                    etype=etype,
                    esubtype=esubtype,
                    parm=parm,
                    name_id=0,
                    long_name_id=0,
                    desc_id=0,
                    name=name,
                    long_name=lname,
                    description=desc,
                )
                self.defs.append(ed)

    def find_weapon(self, weapon_id: int) -> Optional[EntityDef]:
        for d in self.defs:
            if d.etype == 6 and d.esubtype == 1 and d.parm == weapon_id:
                return d
        return None

    def filter(
        self,
        tile: Optional[int] = None,
        etype: Optional[int] = None,
        query: Optional[str] = None,
    ) -> List[EntityDef]:
        res = self.defs
        if tile is not None:
            res = [d for d in res if d.tile_index == tile]
        if etype is not None:
            res = [d for d in res if d.etype == etype]
        if query:
            q_norm = normalize_for_search(query)
            q_raw = query.lower()
            res = [
                d
                for d in res
                if q_raw in d.name.lower()
                or q_raw in d.long_name.lower()
                or q_raw in d.description.lower()
                or (
                    q_norm
                    and (
                        q_norm in normalize_for_search(d.name)
                        or q_norm in normalize_for_search(d.long_name)
                        or q_norm in normalize_for_search(d.description)
                    )
                )
            ]
        return res


# -----------------------------------------------------------------------------
# Mappings, Palettes & Bitshapes
# -----------------------------------------------------------------------------
@dataclass
class ShapeMap:
    ofs: int
    palette: int


class Mappings:
    """Parser for mappings.bin (OE1: res 5007, OE2: res 1004)."""

    def __init__(self, data: bytes):
        (
            self.n_walls,
            self.n_flats,
            self.n_sprites,
            self.n_wremap,
            self.n_fremap,
            self.n_sremap,
        ) = struct.unpack_from("<6I", data, 0)
        pos = 24

        self.wall_maps: List[ShapeMap] = []
        for _ in range(self.n_walls):
            ofs, pal = struct.unpack_from("<II", data, pos)
            pos += 8
            self.wall_maps.append(ShapeMap(ofs=ofs, palette=pal >> 8))

        self.flat_maps: List[ShapeMap] = []
        for _ in range(self.n_flats):
            ofs, pal = struct.unpack_from("<II", data, pos)
            pos += 8
            self.flat_maps.append(ShapeMap(ofs=ofs, palette=pal >> 8))

        self.sprite_maps: List[ShapeMap] = []
        for _ in range(self.n_sprites):
            ofs, pal = struct.unpack_from("<II", data, pos)
            pos += 8
            self.sprite_maps.append(ShapeMap(ofs=ofs, palette=pal >> 8))

        self.wall_remap = list(
            struct.unpack_from(f"<{self.n_wremap}h", data, pos)
        )
        pos += self.n_wremap * 2
        self.flat_remap = list(
            struct.unpack_from(f"<{self.n_fremap}h", data, pos)
        )
        pos += self.n_fremap * 2
        self.sprite_remap = list(
            struct.unpack_from(f"<{self.n_sremap}h", data, pos)
        )
        pos += self.n_sremap * 2


class Palettes:
    """Parser for palettes.bin (OE1: res 5005, OE2: res 1003)."""

    def __init__(self, data: bytes):
        self.num_palettes = struct.unpack_from("<H", data, 0)[0]
        pos = 2
        self.palettes: List[List[Tuple[int, int, int]]] = []
        for _ in range(self.num_palettes):
            count = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            raw_words = struct.unpack_from(f"<{count}H", data, pos)
            pos += count * 2
            rgb_list = []
            for w in raw_words:
                r = ((w >> 11) & 0x1F) << 3
                g = ((w >> 5) & 0x3F) << 2
                b = (w & 0x1F) << 3
                rgb_list.append((r, g, b))
            self.palettes.append(rgb_list)


class Bitshapes:
    """Parser for bitshapes.bin (OE1: res 5006, OE2: res 1005)."""

    def __init__(self, data: bytes):
        self.size = struct.unpack_from("<I", data, 0)[0]
        self.payload = data[4:]

    def get_shape(
        self, ofs: int
    ) -> Optional[Tuple[int, int, int, int, int]]:
        """Returns (stex_idx, first_col, last_col, first_row, last_row)."""
        if ofs + 12 > len(self.payload):
            return None
        stex_idx = struct.unpack_from("<I", self.payload, ofs)[0]
        c1, c2 = self.payload[ofs + 8], self.payload[ofs + 9]
        r1, r2 = self.payload[ofs + 10], self.payload[ofs + 11]
        return (stex_idx, c1, c2, r1, r2)

    def render_silhouette(self, ofs: int, max_width: int = 60) -> str:
        """Render 1-bit ASCII silhouette of the shape mask."""
        sh = self.get_shape(ofs)
        if not sh:
            return ""
        stex, c1, c2, r1, r2 = sh
        w = c2 - c1 + 1
        h = r2 - r1 + 1
        col_bytes = (h + 7) // 8
        grid = [[" " for _ in range(w)] for _ in range(h)]
        raw = self.payload
        mask_start = ofs + 12
        for col in range(w):
            col_off = mask_start + col * col_bytes
            for row in range(h):
                if col_off + row // 8 < len(raw):
                    byte_val = raw[col_off + row // 8]
                    if (byte_val >> (row % 8)) & 1:
                        grid[row][col] = "#"
        lines = []
        step = 2 if h > 20 else 1
        for r in range(0, h, step):
            row_str = "".join(grid[r])
            if row_str.strip():
                lines.append(row_str[:max_width])
        return "\n".join(lines)


# -----------------------------------------------------------------------------
# Map BSP
# -----------------------------------------------------------------------------
@dataclass
class MapLine:
    x1: int
    y1: int
    x2: int
    y2: int
    texture: int
    texture2: int
    flags: int


@dataclass
class MapSprite:
    x: int
    y: int
    z: int
    tile: int
    info: int
    is_placed: bool
    is_wall_attached: bool = False
    wall_dir: Optional[str] = None


@dataclass
class MapData:
    map_id: int
    name: str
    version: int
    hash: int
    floor_color: Tuple[int, int, int]
    ceil_color: Tuple[int, int, int]
    color3: Tuple[int, int, int]
    player_tile: int
    spawn_dir: int
    spawn_tile: int
    floor_height: int
    ceil_height: int
    map_flags_byte: int
    nodes_count: int
    lines: List[MapLine] = field(default_factory=list)
    standing_sprites: List[MapSprite] = field(default_factory=list)
    placed_sprites: List[MapSprite] = field(default_factory=list)
    num_tile_events: int = 0
    num_bytecodes: int = 0
    tile_flags: List[int] = field(default_factory=list)  # 1024 tiles (32x32)
    floor_flats: List[int] = field(default_factory=list)  # 1024 tiles (32x32)
    ceil_flats: List[int] = field(default_factory=list)  # 1024 tiles (32x32)

    def render_ascii(self) -> str:
        """Render a 32x32 grid visualization of the map."""
        grid = [["." for _ in range(32)] for _ in range(32)]

        # Walls & solid tiles
        for idx, fl in enumerate(self.tile_flags):
            x, y = idx % 32, idx // 32
            if fl & 1:  # Blocking / solid
                grid[y][x] = "#"
            elif fl & 2:  # Door or interactive
                grid[y][x] = "+"

        # Standing and placed sprites
        for sp in self.standing_sprites + self.placed_sprites:
            tx = sp.x // 8
            ty = sp.y // 8
            if 0 <= tx < 32 and 0 <= ty < 32:
                if grid[ty][tx] not in ("#", "P"):
                    if sp.tile in (116, 130, 136, 138, 143, 145, 150, 161, 165, 181, 185):
                        grid[ty][tx] = "*"  # Fire/Light emitter
                    elif 0x11 <= sp.tile <= 0x40:
                        grid[ty][tx] = "M"  # Monster
                    else:
                        grid[ty][tx] = "o"  # Other object

        # Player spawn
        px = self.spawn_tile % 32
        py = self.spawn_tile // 32
        if 0 <= px < 32 and 0 <= py < 32:
            grid[py][px] = "P"

        lines = [f"=== {self.name} (Map {self.map_id}) 32x32 Map Grid ==="]
        lines.append("   " + "".join(f"{x % 10}" for x in range(32)))
        for y in range(32):
            lines.append(f"{y:2d} " + "".join(grid[y]))
        lines.append(
            "Legend: '#' Solid wall, '+' Door/Event, '*' Light/Fire, 'M' Monster, 'o' Item/Sprite, 'P' Player spawn"
        )
        return "\n".join(lines)


def parse_map(
    data: bytes,
    map_id: int,
    strings: Optional[StringTable] = None,
    config: Optional[GameConfig] = None,
) -> Optional[MapData]:
    if len(data) < 25:
        return None
    pos = 0
    ver = data[pos]
    pos += 1
    if ver not in (7, 10):
        return None

    is_oe1 = (ver == 7)
    mhash = struct.unpack_from("<I", data, pos)[0]
    pos += 4

    if is_oe1:
        map_name_raw = data[pos : pos + 16]
        pos += 16
        map_name = map_name_raw.split(b"\x00")[0].decode("latin1", "replace").strip()
        if not map_name and config:
            map_name = config.map_names.get(map_id, f"Map_{map_id}")
    else:
        name_id = struct.unpack_from("<h", data, pos)[0]
        pos += 2
        map_str_grp = map_id + 3
        map_name = (
            strings.get(map_str_grp, name_id, clean=True)
            if strings
            else (config.map_names.get(map_id, f"Map_{map_id}") if config else f"Map_{map_id}")
        )
        if not map_name and config:
            map_name = config.map_names.get(map_id, f"Map_{map_id}")

    # Colors
    floor_c = (data[pos + 2], data[pos + 1], data[pos])
    pos += 3
    ceil_c = (data[pos + 2], data[pos + 1], data[pos])
    pos += 3
    color3 = (data[pos + 2], data[pos + 1], data[pos])
    pos += 3

    if is_oe1:
        f1e024 = data[pos]
        pos += 1
        spawn_tile = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        spawn_dir = data[pos]
        pos += 1
        player_tile = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        floor_h = data[pos]
        pos += 1
        ceil_h = data[pos]
        pos += 1
        flags = data[pos]
        pos += 1
    else:
        hdr17628 = data[pos]
        pos += 1
        player_tile = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        spawn_dir = data[pos]
        pos += 1
        spawn_tile = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        floor_h = data[pos]
        pos += 1
        ceil_h = data[pos]
        pos += 1
        flags = data[pos]
        pos += 1

    # Nodes (10 bytes each)
    num_nodes = struct.unpack_from("<h", data, pos)[0]
    pos += 2
    pos += num_nodes * 10

    # Lines (OE1: 9 bytes, OE2: 10 bytes)
    num_lines = struct.unpack_from("<h", data, pos)[0]
    pos += 2
    lines = []
    line_stride = 9 if is_oe1 else 10
    for _ in range(num_lines):
        x1 = data[pos] << 3
        y1 = data[pos + 1] << 3
        x2 = data[pos + 2] << 3
        y2 = data[pos + 3] << 3
        if is_oe1:
            tex1 = data[pos + 4]
            tex2 = 0
            lflags = struct.unpack_from("<I", data, pos + 5)[0]
        else:
            tex1 = data[pos + 4]
            tex2 = data[pos + 5]
            lflags = struct.unpack_from("<I", data, pos + 6)[0]
        pos += line_stride
        lines.append(
            MapLine(
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                texture=tex1,
                texture2=tex2,
                flags=lflags,
            )
        )

    # Sprites
    num_standing = struct.unpack_from("<h", data, pos)[0]
    pos += 2
    num_placed = struct.unpack_from("<h", data, pos)[0]
    pos += 2

    standing_sprites = []
    for _ in range(num_standing):
        sx = data[pos] << 3
        sy = data[pos + 1] << 3
        info = data[pos + 2] | (struct.unpack_from("<h", data, pos + 3)[0] << 16)
        pos += 5
        tile = info & 0xFF
        standing_sprites.append(
            MapSprite(
                x=sx,
                y=sy,
                z=0x20,
                tile=tile,
                info=info,
                is_placed=False,
            )
        )

    placed_sprites = []
    for _ in range(num_placed):
        sx = data[pos] << 3
        sy = data[pos + 1] << 3
        sz = data[pos + 2] if is_oe1 else (data[pos + 2] - 0x20)
        b0 = data[pos + 3]
        b1 = data[pos + 4]
        hi = struct.unpack_from("<h", data, pos + 5)[0]
        pos += 7
        info = b0 | (b1 << 8) | (hi << 16)

        tile = info & 0xFF
        if not is_oe1 and (info & 0x40000):
            tile += 0x101

        is_wall = bool(info & 0x800000)
        wall_dir = None
        if is_wall:
            if info & 0x100000:
                wall_dir = "S"
            elif info & 0x80000:
                wall_dir = "N"
            elif info & 0x200000:
                wall_dir = "E"
            elif info & 0x400000:
                wall_dir = "W"

        placed_sprites.append(
            MapSprite(
                x=sx,
                y=sy,
                z=sz,
                tile=tile,
                info=info,
                is_placed=True,
                is_wall_attached=is_wall,
                wall_dir=wall_dir,
            )
        )

    # Tile events
    num_tile_events = struct.unpack_from("<h", data, pos)[0]
    pos += 2
    if num_tile_events > 0:
        if is_oe1:
            pos += num_tile_events * 4
        else:
            pos += num_tile_events * 2 + num_tile_events * 4

    # Bytecodes / commands
    num_bytecodes = struct.unpack_from("<h", data, pos)[0]
    pos += 2
    if num_bytecodes > 0:
        pos += num_bytecodes * 9

    # OE1 map strings
    if is_oe1:
        num_map_strings = struct.unpack_from("<h", data, pos)[0]
        pos += 2
        for _ in range(num_map_strings):
            slen = struct.unpack_from("<h", data, pos)[0]
            pos += 2 + slen

    # Tile flags
    tile_flags = []
    if is_oe1:
        if pos + 256 <= len(data):
            for _ in range(256):
                b = data[pos]
                pos += 1
                tile_flags.append(b & 3)
                tile_flags.append((b >> 2) & 3)
                tile_flags.append((b >> 4) & 3)
                tile_flags.append(b >> 6)
    else:
        if pos + 512 <= len(data):
            for _ in range(512):
                b = data[pos]
                pos += 1
                tile_flags.append(b & 0x0F)
                tile_flags.append((b >> 4) & 0x0F)

    # Floor and ceil flats (1024 bytes each)
    floor_flats = []
    if pos + 1024 <= len(data):
        floor_flats = list(data[pos : pos + 1024])
        pos += 1024

    ceil_flats = []
    if pos + 1024 <= len(data):
        ceil_flats = list(data[pos : pos + 1024])
        pos += 1024

    return MapData(
        map_id=map_id,
        name=map_name,
        version=ver,
        hash=mhash,
        floor_color=floor_c,
        ceil_color=ceil_c,
        color3=color3,
        player_tile=player_tile,
        spawn_dir=spawn_dir,
        spawn_tile=spawn_tile,
        floor_height=floor_h,
        ceil_height=ceil_h,
        map_flags_byte=flags,
        nodes_count=num_nodes,
        lines=lines,
        standing_sprites=standing_sprites,
        placed_sprites=placed_sprites,
        num_tile_events=num_tile_events,
        num_bytecodes=num_bytecodes,
        tile_flags=tile_flags,
        floor_flats=floor_flats,
        ceil_flats=ceil_flats,
    )


# -----------------------------------------------------------------------------
# High-Level Context / Session
# -----------------------------------------------------------------------------
class OEContext:
    """Unified context holding parsed game assets for Orcs & Elves I / II."""

    def __init__(
        self,
        bar_path: Optional[Path | str] = None,
        game: Optional[str] = None,
    ):
        data_dir = Path(__file__).resolve().parent.parent / "data"

        if bar_path is None:
            if game == "oe1":
                bar_path = data_dir / OE1_CONFIG.bar_default
            elif game == "oe2":
                bar_path = data_dir / OE2_CONFIG.bar_default
            else:
                oe2_bar = data_dir / OE2_CONFIG.bar_default
                oe1_bar = data_dir / OE1_CONFIG.bar_default
                if oe2_bar.exists() and not oe1_bar.exists():
                    bar_path = oe2_bar
                elif oe1_bar.exists() and not oe2_bar.exists():
                    bar_path = oe1_bar
                else:
                    bar_path = oe2_bar if oe2_bar.exists() else oe1_bar

        self.bar = BarArchive(bar_path)
        if game == "oe1":
            self.config = OE1_CONFIG
        elif game == "oe2":
            self.config = OE2_CONFIG
        else:
            self.config = self.bar.detect_game()

        self._strings: Optional[StringTable] = None
        self._entities: Optional[EntityTable] = None
        self._mappings: Optional[Mappings] = None
        self._palettes: Optional[Palettes] = None
        self._bitshapes: Optional[Bitshapes] = None
        self._maps: Dict[int, MapData] = {}

    @property
    def strings(self) -> Optional[StringTable]:
        if self._strings is None and self.config.res_strings is not None:
            raw = self.bar.get(self.config.res_strings)
            if raw:
                self._strings = StringTable(raw)
        return self._strings

    @property
    def entities(self) -> EntityTable:
        if self._entities is None:
            raw = self.bar.get(self.config.res_entities)
            if not raw:
                raise RuntimeError(
                    f"Failed to load entities.bin (res {self.config.res_entities})"
                )
            self._entities = EntityTable(
                raw, self.strings, game_id=self.config.game_id
            )
        return self._entities

    @property
    def mappings(self) -> Mappings:
        if self._mappings is None:
            raw = self.bar.get(self.config.res_mappings)
            if not raw:
                raise RuntimeError(
                    f"Failed to load mappings.bin (res {self.config.res_mappings})"
                )
            self._mappings = Mappings(raw)
        return self._mappings

    @property
    def palettes(self) -> Palettes:
        if self._palettes is None:
            raw = self.bar.get(self.config.res_palettes)
            if not raw:
                raise RuntimeError(
                    f"Failed to load palettes.bin (res {self.config.res_palettes})"
                )
            self._palettes = Palettes(raw)
        return self._palettes

    @property
    def bitshapes(self) -> Bitshapes:
        if self._bitshapes is None:
            raw = self.bar.get(self.config.res_bitshapes)
            if not raw:
                raise RuntimeError(
                    f"Failed to load bitshapes.bin (res {self.config.res_bitshapes})"
                )
            self._bitshapes = Bitshapes(raw)
        return self._bitshapes

    def get_map(self, map_id: int) -> Optional[MapData]:
        if map_id in self._maps:
            return self._maps[map_id]
        res_id = self.config.res_map_base + map_id
        raw = self.bar.get(res_id)
        if not raw:
            return None
        md = parse_map(raw, map_id, self.strings, self.config)
        if md:
            self._maps[map_id] = md
        return md


# Backward compatibility
OE2Context = OEContext


# -----------------------------------------------------------------------------
# CLI Interface
# -----------------------------------------------------------------------------
def cmd_list(ctx: OEContext, args: argparse.Namespace) -> None:
    print(f"Game: {ctx.config.title} ({ctx.config.game_id})")
    print(f"Archive: {ctx.bar.path} ({len(ctx.bar.raw_data)} bytes)")
    print(f"{'ID':>5}  {'Type':>4}  {'Size':>8}  {'Comp':>4}  {'Name'}")
    print("-" * 55)
    for res_id in sorted(ctx.bar.entries.keys()):
        ent = ctx.bar.entries[res_id]
        comp_str = "yes" if ent.is_compressed else "no"
        print(
            f"{ent.id:5d}  {ent.res_type:4d}  {ent.size:8d}  {comp_str:>4}  {ent.name}"
        )


def cmd_extract(ctx: OEContext, args: argparse.Namespace) -> None:
    raw = ctx.bar.get(args.resource)
    if raw is None:
        print(f"Error: resource '{args.resource}' not found in archive.")
        sys.exit(1)
    out_path = Path(args.output) if args.output else Path(f"res_{args.resource}.bin")
    out_path.write_bytes(raw)
    print(f"Extracted {len(raw)} bytes to {out_path}")


def cmd_strings(ctx: OEContext, args: argparse.Namespace) -> None:
    st = ctx.strings
    if st is None:
        print(f"[{ctx.config.title}] strings.bin is not present in this archive.")
        print(
            "Entity names and descriptions are embedded directly in entities.bin (use 'entities' command)."
        )
        mod_file = "orcsandelves.mod" if ctx.config.game_id == "oe1" else "orcsandelves2.mod"
        mod_path = Path(__file__).resolve().parent.parent / "data" / mod_file
        if args.search and mod_path.exists():
            data = mod_path.read_bytes()
            query = args.search.lower()
            results = []
            start = None
            for i, b in enumerate(data):
                if 32 <= b <= 126:
                    if start is None:
                        start = i
                else:
                    if b == 0 and start is not None and i - start >= 3:
                        s = data[start:i].decode("ascii", "replace")
                        if query in s.lower():
                            results.append((start, s))
                    start = None
            print(f"\nSearch results from {mod_file} ({len(results)} matches):")
            for off, s in results:
                print(f"  [Offset 0x{off:05x}]: {clean_text(s)}")
        return

    if args.search:
        results = st.search(args.search)
        print(f"Found {len(results)} matches for '{args.search}':")
        for g, idx, text in results:
            print(f"  [Group {g:2d}, Idx {idx:3d}]: {clean_text(text)}")
        return

    if args.group is not None:
        g = args.group
        if not (0 <= g < len(st.groups)):
            print(f"Invalid group {g} (valid: 0..{len(st.groups)-1})")
            return
        print(f"=== Group {g} ({len(st.groups[g])} strings) ===")
        for idx, text in enumerate(st.groups[g]):
            if text:
                print(f"  [{idx:3d}]: {clean_text(text)}")
        return

    print(f"=== {ctx.config.title} Strings Summary ({len(st.groups)} groups) ===")
    for idx, grp in enumerate(st.groups):
        first = clean_text(grp[0]) if grp and grp[0] else "(empty)"
        if len(first) > 40:
            first = first[:37] + "..."
        print(f"  Group {idx:2d}: {len(grp):3d} strings | Sample: {first}")


def cmd_entities(ctx: OEContext, args: argparse.Namespace) -> None:
    ed_list = ctx.entities.filter(
        tile=args.tile, etype=args.type, query=args.search
    )
    print(
        f"=== {ctx.config.title} Entities ({len(ed_list)} of {len(ctx.entities.defs)}) ==="
    )
    print(
        f"{'Idx':>4} {'Tile':>4} {'Type':>5} {'Parm':>5} {'Name':<18} {'Long Name':<20} {'Description'}"
    )
    print("-" * 80)
    for ed in ed_list:
        name = clean_text(ed.name)
        lname = clean_text(ed.long_name)
        desc = clean_text(ed.description)
        if len(desc) > 30:
            desc = desc[:27] + "..."
        t_str = f"{ed.etype}:{ed.esubtype}"
        print(
            f"{ed.index:4d} {ed.tile_index:4d} {t_str:>5} {ed.parm:5d} {name:<18} {lname:<20} {desc}"
        )


def cmd_weapons(ctx: OEContext, args: argparse.Namespace) -> None:
    print(f"=== {ctx.config.title} Weapons & Equipment ===")
    print(
        f"{'WID':>4} {'SubID':>5} {'Tile':>4} {'Name':<16} {'Long Name':<20} {'Description'}"
    )
    print("-" * 75)
    max_weapons = 8 if ctx.config.game_id == "oe1" else 11
    for w in range(max_weapons):
        ed = ctx.entities.find_weapon(w)
        if ed:
            name = clean_text(ed.name)
            lname = clean_text(ed.long_name)
            desc = clean_text(ed.description)
            if len(desc) > 30:
                desc = desc[:27] + "..."
            print(
                f"{w:4d} {ed.sub_id:5d} {ed.tile_index:4d} {name:<16} {lname:<20} {desc}"
            )
        else:
            print(f"{w:4d}   (not defined in entities.bin)")


def cmd_map(ctx: OEContext, args: argparse.Namespace) -> None:
    map_id = None
    map_arg = str(args.map).strip()

    if map_arg.isdigit():
        num = int(map_arg)
        # Check if direct resource ID
        if ctx.config.game_id == "oe1" and 6000 <= num <= 6011:
            map_id = num - 5999
        elif ctx.config.game_id == "oe2" and 2000 <= num <= 2014:
            map_id = num - 1999
        else:
            map_id = num
    else:
        # Match by name
        m_name = map_arg.lower()
        for mid, name in ctx.config.map_names.items():
            if m_name in name.lower():
                map_id = mid
                break

    if map_id is None:
        print(f"Could not identify map '{args.map}' for {ctx.config.title}")
        print("Available maps:")
        for mid, name in sorted(ctx.config.map_names.items()):
            res_id = ctx.config.res_map_base + mid
            print(f"  {mid:2d} (Res {res_id}): {name}")
        return

    md = ctx.get_map(map_id)
    if not md:
        print(f"Map {map_id} could not be parsed.")
        return

    res_id = ctx.config.res_map_base + md.map_id
    print(f"=== Map {md.map_id} (Res {res_id}): {md.name} [{ctx.config.title}] ===")
    print(f"  Version: {md.version}, Hash: 0x{md.hash:08X}")
    print(
        f"  Floor Color (RGB): {md.floor_color}, Ceil Color (RGB): {md.ceil_color}"
    )
    print(
        f"  Spawn Tile: {md.spawn_tile} (x={md.spawn_tile%32}, y={md.spawn_tile//32}), Dir: {md.spawn_dir}"
    )
    print(
        f"  Nodes: {md.nodes_count}, Lines: {len(md.lines)}, Events: {md.num_tile_events}, Bytecodes: {md.num_bytecodes}"
    )
    print(
        f"  Standing Sprites: {len(md.standing_sprites)}, Placed Sprites: {len(md.placed_sprites)}"
    )

    if args.ascii:
        print()
        print(md.render_ascii())

    if args.sprites:
        print("\nPlaced Sprites:")
        print(f"  {'Tile':>4} {'Grid(X,Y)':>10} {'Height(Z)':>9} {'Wall Attached':<14} {'Name'}")
        print("  " + "-" * 55)
        for sp in md.placed_sprites:
            gx, gy = sp.x // 8, sp.y // 8
            w_str = f"Yes ({sp.wall_dir})" if sp.is_wall_attached else "No"
            ed_list = ctx.entities.filter(tile=sp.tile)
            name = clean_text(ed_list[0].name) if ed_list else ""
            print(
                f"  {sp.tile:4d} {f'({gx},{gy})':>10} {sp.z:9d} {w_str:<14} {name}"
            )


def cmd_emitters(ctx: OEContext, args: argparse.Namespace) -> None:
    """Analyze light emitter candidate tiles and occurrences across campaign maps."""
    map_range = ctx.config.campaign_map_range
    start_m, end_m = map_range.start, map_range.stop - 1
    print(
        f"=== Light Emitter Analysis across {ctx.config.title} Campaign Maps ({start_m}..{end_m}) ==="
    )

    candidate_tiles = ctx.config.candidate_emitters
    tile_counts: Dict[int, Dict[int, int]] = {t: {} for t in candidate_tiles}

    for mid in map_range:
        md = ctx.get_map(mid)
        if not md:
            continue
        all_sprites = md.standing_sprites + md.placed_sprites
        for sp in all_sprites:
            if sp.tile in candidate_tiles:
                tile_counts[sp.tile][mid] = tile_counts[sp.tile].get(mid, 0) + 1

    print(f"{'Tile':>4}  {'Description':<32}  {'Maps & Counts'}")
    print("-" * 65)
    for tile, desc in candidate_tiles.items():
        counts = tile_counts[tile]
        if counts:
            map_str = ", ".join(f"M{m}:{c}" for m, c in sorted(counts.items()))
        else:
            map_str = f"(none placed directly in M{start_m}-M{end_m})"
        print(f"{tile:4d}  {desc:<32}  {map_str}")


def cmd_tile(ctx: OEContext, args: argparse.Namespace) -> None:
    tile = args.tile
    print(f"=== Tile {tile} Report [{ctx.config.title}] ===")

    # 1. Entity definitions using this tile
    ed_list = ctx.entities.filter(tile=tile)
    if ed_list:
        print(f"\nAssociated Entities ({len(ed_list)}):")
        for ed in ed_list:
            print(
                f"  [{ed.index}] Type {ed.etype}:{ed.esubtype}, Parm {ed.parm}: {clean_text(ed.name)} / {clean_text(ed.long_name)}"
            )
            if ed.description:
                print(f"      Description: {clean_text(ed.description)}")
    else:
        print("\nNo entities directly specify this tileIndex.")

    # 2. Mappings and sprite frames
    if tile < len(ctx.mappings.sprite_remap):
        remap_base = ctx.mappings.sprite_remap[tile]
        remap_next = (
            ctx.mappings.sprite_remap[tile + 1]
            if tile + 1 < len(ctx.mappings.sprite_remap)
            else len(ctx.mappings.sprite_maps)
        )
        frame_count = max(0, remap_next - remap_base)
        print(
            f"\nSprite Frames (Remap base: {remap_base}, Count: {frame_count}):"
        )
        for f in range(remap_base, min(remap_next, remap_base + 16)):
            sm = ctx.mappings.sprite_maps[f]
            sh = ctx.bitshapes.get_shape(sm.ofs)
            if sh:
                stex, c1, c2, r1, r2 = sh
                w = c2 - c1 + 1
                h = r2 - r1 + 1
                print(
                    f"  Frame {f - remap_base}: ofs={sm.ofs}, pal={sm.palette}, stex={stex}, size={w}x{h} (cols {c1}..{c2}, rows {r1}..{r2})"
                )
            else:
                print(f"  Frame {f - remap_base}: ofs={sm.ofs}, pal={sm.palette}")

        if args.ascii and frame_count > 0:
            sm0 = ctx.mappings.sprite_maps[remap_base]
            print("\nFrame 0 Silhouette Preview:")
            print(ctx.bitshapes.render_silhouette(sm0.ofs))

    # 3. Placement in campaign maps
    map_range = ctx.config.campaign_map_range
    start_m, end_m = map_range.start, map_range.stop - 1
    print(f"\nOccurrences in Campaign Maps ({start_m}..{end_m}):")
    total_found = 0
    for mid in map_range:
        md = ctx.get_map(mid)
        if not md:
            continue
        matches = [
            sp
            for sp in (md.standing_sprites + md.placed_sprites)
            if sp.tile == tile
        ]
        if matches:
            total_found += len(matches)
            coords = ", ".join(f"({sp.x//8},{sp.y//8})" for sp in matches[:6])
            if len(matches) > 6:
                coords += f" ... (+{len(matches)-6} more)"
            print(f"  Map {mid} ({md.name}): {len(matches)} placed at {coords}")
    if total_found == 0:
        print(f"  (not placed in maps {start_m}..{end_m})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OEData: Data Inspection Tool for Orcs & Elves / Orcs & Elves II",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--game",
        choices=["oe1", "oe2"],
        default=None,
        help="Target game edition (oe1 or oe2; auto-detected if omitted)",
    )
    parser.add_argument(
        "--bar",
        type=str,
        default=None,
        help="Path to .bar archive (default: data/orcsandelves[2].bar)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommand to run")

    # list
    subparsers.add_parser("list", help="List all resources in the archive")

    # extract
    p_ext = subparsers.add_parser("extract", help="Extract a resource to file")
    p_ext.add_argument("resource", help="Resource ID or file name")
    p_ext.add_argument("-o", "--output", help="Output file path")

    # strings
    p_str = subparsers.add_parser("strings", help="Inspect strings (strings.bin or .mod)")
    p_str.add_argument("group", nargs="?", type=int, help="String group (OE2: 0..20)")
    p_str.add_argument(
        "-s", "--search", type=str, help="Search string across all groups / mod data"
    )

    # entities
    p_ent = subparsers.add_parser("entities", help="Inspect entities.bin")
    p_ent.add_argument("-t", "--tile", type=int, help="Filter by tileIndex")
    p_ent.add_argument("--type", type=int, help="Filter by eType")
    p_ent.add_argument(
        "-s", "--search", type=str, help="Search by name or description"
    )

    # weapons
    subparsers.add_parser("weapons", help="List player weapons and stats")

    # map
    p_map = subparsers.add_parser("map", help="Inspect map BSP")
    p_map.add_argument("map", help="Map number (e.g. 1..11/14), resource ID (e.g. 6000, 2000), or name")
    p_map.add_argument(
        "--ascii", action="store_true", help="Print 32x32 ASCII visualization"
    )
    p_map.add_argument(
        "--sprites", action="store_true", help="List all placed sprites"
    )

    # emitters
    subparsers.add_parser(
        "emitters", help="Analyze light emitter sources across campaign maps"
    )

    # tile
    p_tile = subparsers.add_parser(
        "tile", help="Inspect a specific sprite/tile ID"
    )
    p_tile.add_argument("tile", type=int, help="Tile ID (e.g. 130, 136, 145, 165)")
    p_tile.add_argument(
        "--ascii", action="store_true", help="Render silhouette of frame 0"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    try:
        ctx = OEContext(bar_path=args.bar, game=args.game)
    except Exception as e:
        print(f"Error initializing OEContext: {e}")
        sys.exit(1)

    cmds = {
        "list": cmd_list,
        "extract": cmd_extract,
        "strings": cmd_strings,
        "entities": cmd_entities,
        "weapons": cmd_weapons,
        "map": cmd_map,
        "emitters": cmd_emitters,
        "tile": cmd_tile,
    }

    cmd_fn = cmds.get(args.command)
    if cmd_fn:
        cmd_fn(ctx, args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
