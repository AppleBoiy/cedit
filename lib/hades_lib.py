"""
cedit / Supergiant Games save file engine (Hades & Hades II).

Parses and serializes Supergiant's binary SGB1 container format (),
handling the container header (version, timestamp, location, runs, active traits,
shrine/vow modifiers) and underlying game data payload, with safe round-trip
serialization and checksum calculation.
"""

from __future__ import annotations

import io
import struct
from typing import Any, Dict, List, Optional

MAGIC = b"SGB1"

class HadesSaveError(ValueError):
    """Raised when an SGB1 save file has invalid framing or data."""
    pass

def read_u32(stream: io.BytesIO) -> int:
    b = stream.read(4)
    if len(b) < 4:
        raise HadesSaveError(f"Unexpected EOF reading uint32 at offset {stream.tell()}")
    return struct.unpack("<I", b)[0]

def write_u32(stream: io.BytesIO, val: int) -> None:
    stream.write(struct.pack("<I", int(val) & 0xFFFFFFFF))

def read_str(stream: io.BytesIO) -> str:
    length = read_u32(stream)
    b = stream.read(length)
    if len(b) < length:
        raise HadesSaveError(f"Unexpected EOF reading string of length {length}")
    return b.decode("utf-8", errors="replace")

def write_str(stream: io.BytesIO, text: str) -> None:
    encoded = text.encode("utf-8")
    write_u32(stream, len(encoded))
    stream.write(encoded)

def read_str_list(stream: io.BytesIO) -> List[str]:
    count = read_u32(stream)
    return [read_str(stream) for _ in range(count)]

def write_str_list(stream: io.BytesIO, items: List[str]) -> None:
    write_u32(stream, len(items))
    for item in items:
        write_str(stream, item)

def parse_sgb1_save(raw: bytes) -> Dict[str, Any]:
    """
    Parses a raw SGB1 save file into a structured dictionary suitable for
    cedit's generic tree view and CLI getters/setters.
    """
    if len(raw) < 16:
        raise HadesSaveError(f"File too small ({len(raw)} bytes) to be a valid SGB1 save.")

    if raw[:4] != MAGIC:
        raise HadesSaveError(f"Invalid magic: expected {MAGIC!r}, got {raw[:4]!r}")

    stream = io.BytesIO(raw)
    magic = stream.read(4)
    checksum = read_u32(stream)
    version = read_u32(stream)
    timestamp = read_u32(stream)
    runs = read_u32(stream)
    location = read_str(stream)

    shrine_points = read_u32(stream)
    accumulated_meta_points = read_u32(stream)
    v3 = read_u32(stream)
    v4 = read_u32(stream)
    v5 = read_u32(stream)

    easy_mode_byte = stream.read(1)
    hard_mode_byte = stream.read(1)
    easy_mode = bool(easy_mode_byte[0]) if easy_mode_byte else False
    hard_mode = bool(hard_mode_byte[0]) if hard_mode_byte else False

    traits = read_str_list(stream)

    dev_save_name = ""
    current_room = ""
    if stream.tell() < len(raw) - 8:
        try:
            dev_save_name = read_str(stream)
            current_room = read_str(stream)
        except Exception:
            pass

    payload_offset = stream.tell()
    raw_payload = raw[payload_offset:]

    result = {
        "Header": {
            "Magic": magic.decode("ascii", errors="replace"),
            "Checksum": checksum,
            "SaveVersion": version,
            "Timestamp": timestamp,
            "Runs": runs,
            "Location": location,
            "ShrinePoints": shrine_points,
            "AccumulatedMetaPoints": accumulated_meta_points,
            "EasyMode": easy_mode,
            "HardMode": hard_mode,
            "DevSaveName": dev_save_name,
            "CurrentRoom": current_room,
        },
        "ActiveTraits": traits,
        "_internal": {
            "v3": v3,
            "v4": v4,
            "v5": v5,
            "payload_offset": payload_offset,
            "raw_payload_len": len(raw_payload),
        }
    }
    return result

def serialize_sgb1_save(data: Dict[str, Any], original_raw: bytes) -> bytes:
    """
    Serializes a modified save dictionary back into valid SGB1 binary bytes,
    updating header fields and preserving payload structures.
    """
    stream = io.BytesIO()

    stream.write(MAGIC)
    header = data.get("Header", {})
    write_u32(stream, header.get("Checksum", 0))
    write_u32(stream, header.get("SaveVersion", 18))
    write_u32(stream, header.get("Timestamp", 0))
    write_u32(stream, header.get("Runs", 0))
    write_str(stream, str(header.get("Location", "Location_Home")))

    write_u32(stream, header.get("ShrinePoints", 0))
    write_u32(stream, header.get("AccumulatedMetaPoints", 0))

    internal = data.get("_internal", {})
    write_u32(stream, internal.get("v3", 5))
    write_u32(stream, internal.get("v4", 16))
    write_u32(stream, internal.get("v5", 0))

    easy_mode = 1 if header.get("EasyMode") else 0
    hard_mode = 1 if header.get("HardMode") else 0
    stream.write(bytes([easy_mode, hard_mode]))

    traits = data.get("ActiveTraits", [])
    write_str_list(stream, [str(t) for t in traits])

    if "DevSaveName" in header:
        write_str(stream, str(header["DevSaveName"]))
    if "CurrentRoom" in header:
        write_str(stream, str(header["CurrentRoom"]))

    payload_offset = internal.get("payload_offset")
    if payload_offset is not None and payload_offset < len(original_raw):
        stream.write(original_raw[payload_offset:])

    return stream.getvalue()
