"""
cedit game profile: Hades (Supergiant Games)

Save format: Supergiant Binary v1 (SGB1) holding save metadata, run history,
heat/shrine levels, and game progression state.
"""
from pathlib import Path
from lib.base import GameProfile
from lib import hades_lib

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "hades.json"

class HadesData(dict):
    """Parsed representation of an SGB1 save, preserving original raw bytes."""
    pass

def loads(raw_bytes: bytes) -> HadesData:
    parsed = hades_lib.parse_sgb1_save(raw_bytes)
    wrapped = HadesData(parsed)
    wrapped._raw = bytes(raw_bytes)
    return wrapped

def dumps(data: HadesData) -> bytes:
    if not isinstance(data, HadesData) or not hasattr(data, "_raw"):
        raise ValueError(
            "This save was not loaded through cedit's Hades profile (missing original file bytes)."
        )
    return hades_lib.serialize_sgb1_save(data, data._raw)

def read_only_check(container, key, value) -> bool:
    if isinstance(key, str) and key.startswith("_"):
        return True
    return False

PROFILE = GameProfile.from_config(
    _CONFIG_PATH,
    custom_loads=loads,
    custom_dumps=dumps,
)
PROFILE.binary = True
PROFILE.read_only_check = read_only_check
