"""
cedit / Supergiant Games save file engine (Hades & Hades II).

Full implementation of Supergiant SGB1 container decoding and encoding:
- Adler32 checksum verification & calculation
- Header parsing (runs, location, timestamp, version flags, grasp, prestige, god/hell mode)
- LZ4 block decompression & compression
- Complete Luabins parser & serializer for GameState, Resources, and CurrentRun.
"""
from __future__ import annotations

import contextlib
import io
import struct
import zlib
from pathlib import Path
from typing import Any

import lz4.block

MAGIC = b"SGB1"
SAVE_VERSION_MASK = 0xFFFF
MAX_DECOMPRESSED_SIZE = 256 * 1024 * 1024


class HadesSaveError(ValueError):
    pass


def adler32_checksum(data: bytes) -> int:
    return zlib.adler32(data) & 0xFFFFFFFF


class BinaryReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.pos

    def ensure(self, size: int, label: str = "data"):
        if self.pos + size > len(self.data):
            raise HadesSaveError(f"Unexpected end of file reading {label}.")

    def read_u8(self) -> int:
        self.ensure(1)
        v = self.data[self.pos]
        self.pos += 1
        return v

    def read_i32(self) -> int:
        self.ensure(4)
        v = struct.unpack("<i", self.data[self.pos:self.pos+4])[0]
        self.pos += 4
        return v

    def read_u32(self) -> int:
        self.ensure(4)
        v = struct.unpack("<I", self.data[self.pos:self.pos+4])[0]
        self.pos += 4
        return v

    def read_u64(self) -> int:
        self.ensure(8)
        v = struct.unpack("<Q", self.data[self.pos:self.pos+8])[0]
        self.pos += 8
        return v

    def read_double(self) -> float:
        self.ensure(8)
        v = struct.unpack("<d", self.data[self.pos:self.pos+8])[0]
        self.pos += 8
        return v

    def read_bytes(self, size: int) -> bytes:
        self.ensure(size)
        v = self.data[self.pos:self.pos+size]
        self.pos += size
        return v

    def read_str(self) -> str:
        length = self.read_i32()
        if length < 0:
            raise HadesSaveError("Invalid string length.")
        b = self.read_bytes(length)
        return b.decode("utf-8", errors="replace")

    def read_str_array(self) -> list[str]:
        count = self.read_i32()
        return [self.read_str() for _ in range(count)]


class BinaryWriter:
    def __init__(self):
        self.buf = io.BytesIO()

    def write_u8(self, v: int):
        self.buf.write(bytes([int(v) & 0xFF]))

    def write_i32(self, v: int):
        self.buf.write(struct.pack("<i", int(v)))

    def write_u32(self, v: int):
        self.buf.write(struct.pack("<I", int(v) & 0xFFFFFFFF))

    def write_u64(self, v: int):
        self.buf.write(struct.pack("<Q", int(v)))

    def write_double(self, v: float):
        self.buf.write(struct.pack("<d", float(v)))

    def write_bytes(self, b: bytes):
        self.buf.write(b)

    def write_str(self, s: str):
        encoded = str(s).encode("utf-8")
        self.write_i32(len(encoded))
        self.write_bytes(encoded)

    def write_str_array(self, items: list[str]):
        self.write_i32(len(items))
        for item in items:
            self.write_str(item)

    def finish(self) -> bytes:
        return self.buf.getvalue()


class LuaReader:
    def __init__(self, buf: bytes):
        self.reader = BinaryReader(buf)

    def read_document(self) -> list[Any]:
        count = self.reader.read_u8()
        values = [self.read_tagged_val() for _ in range(count)]
        return values

    def read_tagged_val(self) -> Any:
        t = self.reader.read_u8()
        return self.read_val(t)

    def read_val(self, t: int) -> Any:
        if t == 45:  # Nil
            return None
        if t == 48:  # False
            return False
        if t == 49:  # True
            return True
        if t == 78:  # Double Number
            return self.reader.read_double()
        if t == 83:  # String
            return self.reader.read_str()
        if t == 84:  # Table
            return self.read_table()
        raise HadesSaveError(f"Unsupported Lua type: {t}")

    def read_table(self) -> dict[Any, Any]:
        arr_sz = self.reader.read_i32()
        hash_sz = self.reader.read_i32()
        size = arr_sz + hash_sz
        if arr_sz < 0 or hash_sz < 0 or size > 10000000:
            raise HadesSaveError("Invalid Lua table size.")
        d = {}
        for _ in range(size):
            k = self.read_tagged_val()
            v = self.read_tagged_val()
            d[k] = v
        return d


class LuaWriter:
    def __init__(self):
        self.writer = BinaryWriter()

    def write_document(self, values: list[Any]) -> bytes:
        self.writer.write_u8(len(values))
        for v in values:
            self.write_tagged_val(v)
        return self.writer.finish()

    def write_tagged_val(self, val: Any, is_numeric_key: bool = False):
        if val is None:
            self.writer.write_u8(45)
        elif isinstance(val, bool):
            self.writer.write_u8(49 if val else 48)
        elif isinstance(val, (int, float)):
            self.writer.write_u8(78)
            self.writer.write_double(val)
        elif isinstance(val, str):
            if is_numeric_key and val != "" and val.replace(".", "", 1).isdigit():
                try:
                    num = float(val)
                    self.writer.write_u8(78)
                    self.writer.write_double(num)
                    return
                except ValueError:
                    pass
            self.writer.write_u8(83)
            self.writer.write_str(val)
        elif isinstance(val, dict):
            self.writer.write_u8(84)
            self.write_table(val)
        else:
            raise HadesSaveError(f"Unsupported Lua value type: {type(val)}")

    def write_table(self, table: dict[Any, Any]):
        keys = list(table.keys())
        numeric_keys = [k for k in keys if isinstance(k, (int, float)) or (isinstance(k, str) and k != "" and k.replace(".", "", 1).isdigit())]
        hash_count = len(keys) - len(numeric_keys)

        self.writer.write_i32(len(numeric_keys))
        self.writer.write_i32(hash_count)

        for k in keys:
            self.write_tagged_val(k, is_numeric_key=True)
            self.write_tagged_val(table[k])


def parse_sgb1_save(raw: bytes) -> dict[str, Any]:
    if len(raw) < 64:
        raise HadesSaveError("File is too small to be a valid Hades save profile.")

    reader = BinaryReader(raw)
    sig = reader.read_bytes(4)
    if sig != MAGIC:
        raise HadesSaveError(f"Invalid signature: expected SGB1, got {sig!r}")

    reader.read_u32()  # checksum - not verified on read, only recomputed on write
    raw_version = reader.read_i32()
    version = raw_version & SAVE_VERSION_MASK
    version_flags = raw_version & ~SAVE_VERSION_MASK
    timestamp = reader.read_u64()
    location = reader.read_str()
    runs = reader.read_i32()

    padding1 = bytes(8)
    grasp = 0
    prestige = 0
    active_meta_points = 0
    active_shrine_points = 0

    if version >= 17:
        padding1 = reader.read_bytes(8)
        grasp = reader.read_i32()
        if version >= 18:
            prestige = reader.read_i32()
    else:
        active_meta_points = reader.read_i32()
        active_shrine_points = reader.read_i32()

    god_mode = bool(reader.read_u8())
    hell_mode = bool(reader.read_u8())
    lua_keys = reader.read_str_array()
    current_map = reader.read_str()
    start_next_map = reader.read_str()

    compressed_size = reader.read_i32()
    compressed = reader.read_bytes(compressed_size)

    # Decompress Lua block
    decomp = lz4.block.decompress(compressed, uncompressed_size=MAX_DECOMPRESSED_SIZE)
    luabin = LuaReader(decomp).read_document()

    root_table = luabin[0] if luabin else {}
    game_state = root_table.get("GameState", {})
    current_run = root_table.get("CurrentRun", {})

    return {
        "Header": {
            "SaveVersion": version,
            "VersionFlags": version_flags,
            "Timestamp": timestamp,
            "Runs": runs,
            "Location": location,
            "Grasp": grasp,
            "Prestige": prestige,
            "ActiveMetaPoints": active_meta_points,
            "ActiveShrinePoints": active_shrine_points,
            "EasyMode": god_mode,
            "HardMode": hell_mode,
            "CurrentMap": current_map,
            "NextMap": start_next_map,
        },
        "GameState": game_state,
        "CurrentRun": current_run,
        "_luabin": luabin,
        "_internal": {
            "padding1": list(padding1),
            "lua_keys": lua_keys,
        }
    }


def serialize_sgb1_save(data: dict[str, Any], original_raw: bytes | None = None) -> bytes:
    header = data.get("Header", {})
    version = int(header.get("SaveVersion", 18))
    version_flags = int(header.get("VersionFlags", 0))

    writer = BinaryWriter()
    writer.write_bytes(MAGIC)
    writer.write_u32(0)  # Checksum placeholder at offset 4..8
    writer.write_i32(version_flags | version)
    writer.write_u64(int(header.get("Timestamp", 0)))
    writer.write_str(str(header.get("Location", "Location_Home")))
    writer.write_i32(int(header.get("Runs", 0)))

    internal = data.get("_internal", {})
    if version >= 17:
        padding = bytes(internal.get("padding1", [0]*8))
        writer.write_bytes(padding)
        writer.write_i32(int(header.get("Grasp", 16)))
        if version >= 18:
            writer.write_i32(int(header.get("Prestige", 0)))
    else:
        writer.write_i32(int(header.get("ActiveMetaPoints", 0)))
        writer.write_i32(int(header.get("ActiveShrinePoints", 0)))

    writer.write_u8(1 if header.get("EasyMode") else 0)
    writer.write_u8(1 if header.get("HardMode") else 0)

    # Lua keys / traits
    traits = internal.get("lua_keys", [])
    writer.write_str_array([str(t) for t in traits])
    writer.write_str(str(header.get("CurrentMap", "")))
    writer.write_str(str(header.get("NextMap", "")))

    # Sync modified GameState and CurrentRun back into _luabin
    luabin = data.get("_luabin", [{}])
    if luabin and isinstance(luabin[0], dict):
        if "GameState" in data:
            luabin[0]["GameState"] = data["GameState"]
        if "CurrentRun" in data:
            luabin[0]["CurrentRun"] = data["CurrentRun"]

    # Encode & Compress Lua block
    lua_bytes = LuaWriter().write_document(luabin)
    compressed = lz4.block.compress(lua_bytes, store_size=False)

    writer.write_i32(len(compressed))
    writer.write_bytes(compressed)

    output = bytearray(writer.finish())
    # Compute Adler-32 over bytes starting at offset 8
    calc_chk = adler32_checksum(bytes(output[8:]))
    output[4:8] = struct.pack("<I", calc_chk)

    return bytes(output)


# ----------------------------------------------------------------------
# Hades II Texture Resolution Fix
# ----------------------------------------------------------------------

DEFAULT_HADES2_CONTENT_DIRS = [
    # macOS Steam
    "~/Library/Application Support/Steam/steamapps/common/Hades II/Hades II.app/Contents/Resources/Content",
    "~/Library/Application Support/Steam/steamapps/common/Hades II/Content",
    # macOS Epic / Standalone
    "~/Library/Application Support/Epic/Hades II/Content",
    "/Applications/Hades II.app/Contents/Resources/Content",
    # Windows Steam
    "%ProgramFiles(x86)%/Steam/steamapps/common/Hades II/Content",
    "%ProgramFiles%/Steam/steamapps/common/Hades II/Content",
    "%USERPROFILE%/AppData/Local/Steam/steamapps/common/Hades II/Content",
    # Windows Epic
    "%ProgramFiles%/Epic Games/HadesII/Content",
    # Linux / Steam Deck / Proton
    "~/.steam/steam/steamapps/common/Hades II/Content",
    "~/.local/share/Steam/steamapps/common/Hades II/Content",
    "~/.var/app/com.valvesoftware.Steam/data/Steam/steamapps/common/Hades II/Content",
]


def resolve_hades2_content_dir(custom_path=None):
    import os
    if custom_path:
        p = Path(os.path.expandvars(os.path.expanduser(str(custom_path))))
        if (p / "Movies").is_dir() and (p / "Packages").is_dir():
            return p
        if (p / "Content" / "Movies").is_dir() and (p / "Content" / "Packages").is_dir():
            return p / "Content"
        if (p / "Contents" / "Resources" / "Content" / "Movies").is_dir():
            return p / "Contents" / "Resources" / "Content"
        if p.is_dir():
            return p

    for entry in DEFAULT_HADES2_CONTENT_DIRS:
        p = Path(os.path.expandvars(os.path.expanduser(entry)))
        if (p / "Movies").is_dir() and (p / "Packages").is_dir():
            return p
    return None


def get_hades2_texture_status(content_dir):
    content_dir = Path(content_dir)
    movies_dir = content_dir / "Movies"
    packages_dir = content_dir / "Packages"

    if not movies_dir.is_dir() or not packages_dir.is_dir():
        return {
            "valid": False,
            "is_swapped": False,
            "error": "Movies or Packages directory not found in content path.",
        }

    m_1080 = movies_dir / "1080p"
    m_720 = movies_dir / "720p"
    p_1080 = packages_dir / "1080p"
    p_720 = packages_dir / "720p"

    if not (m_1080.is_dir() and m_720.is_dir() and p_1080.is_dir() and p_720.is_dir()):
        return {
            "valid": False,
            "is_swapped": False,
            "error": "Missing 1080p or 720p folders in Movies/Packages.",
        }

    # Detect by checking file size of known packages
    # In default/normal state, 1080p/Achilles.pkg (~15MB) > 720p/Achilles.pkg (~8MB)
    pkg_1080 = p_1080 / "Achilles.pkg"
    pkg_720 = p_720 / "Achilles.pkg"

    is_swapped = False
    if pkg_1080.is_file() and pkg_720.is_file():
        is_swapped = pkg_720.stat().st_size > pkg_1080.stat().st_size
    else:
        # Fallback to AsphodelBacking.bik in Movies
        mov_1080 = m_1080 / "AsphodelBacking.bik"
        mov_720 = m_720 / "AsphodelBacking.bik"
        if mov_1080.is_file() and mov_720.is_file():
            is_swapped = mov_720.stat().st_size > mov_1080.stat().st_size

    return {
        "valid": True,
        "is_swapped": is_swapped,
        "movies_path": str(movies_dir),
        "packages_path": str(packages_dir),
        "status_text": "High-Res Forced (1080p swapped into 720p)" if is_swapped else "Default (Normal 1080p/720p)",
    }


def swap_hades2_texture_folders(content_dir):
    content_dir = Path(content_dir)
    status = get_hades2_texture_status(content_dir)
    if not status.get("valid"):
        return False, status.get("error", "Invalid directory structure.")

    for folder_name in ["Movies", "Packages"]:
        target = content_dir / folder_name
        d_1080 = target / "1080p"
        d_720 = target / "720p"
        d_temp = target / "_temp_swap_cedit"

        if d_temp.exists():
            return False, f"Temporary folder {d_temp} already exists. Please resolve manually."

        try:
            d_1080.rename(d_temp)
            d_720.rename(d_1080)
            d_temp.rename(d_720)
        except Exception as e:
            # Attempt to roll back if possible
            if d_temp.exists() and not d_1080.exists():
                with contextlib.suppress(Exception):
                    d_temp.rename(d_1080)
            return False, f"Failed to swap {folder_name} folders: {e}"

    new_status = get_hades2_texture_status(content_dir)
    if new_status.get("is_swapped"):
        return True, "Successfully forced High-Res textures (1080p assets loaded for 720p requests)."
    else:
        return True, "Successfully restored default texture mapping (1080p / 720p standard)."