"""
cedit / Octopath Traveler: vendored save-parsing internals.

This module is a trimmed adaptation of the save-parsing logic (parse_save
and its dependencies) from AppleBoiy/octopath-save-editor
(https://github.com/AppleBoiy/octopath-save-editor), licensed GPL-3.0 (see
that repository's LICENSE file for full terms). Credit for reverse-
engineering the GVAS/UE4.27 tagged-property layout for both Octopath
Traveler (Steam app 921570) and Octopath Traveler II (Steam app 1971870),
including the OT1/OT2 property-name differences and the backpack layout
difference, belongs entirely to that project.

What's kept here: parsing (parse_save and everything it needs) so cedit
can browse a save's full contents - money, both games' character rosters
(stats, stat bonuses, jobs, equipment), inventory, and (OT1) the
tame-monster "Capture" roster - plus the offset/catalog bookkeeping
(_offsets, _inventory_slots, _inventory_empty, equipment slots' _offset,
capture slots' _offsets) games/octopath.py's writer needs to safely patch
scalar fields back in place, ported from the same ideas as upstream's own
normalize_edits/apply_edits (item/monster catalog validation, equipment
category matching, count bounds, empty-slot allocation for a new
inventory item) but adapted to cedit's "mutate the parsed dict, dumps()
diffs it against a fresh reparse of the pristine bytes" editing model
instead of upstream's key-path edits-dict model. See games/octopath.py's
own module docstring for exactly what is and isn't editable, and why.

What's intentionally left out: second-job assignment, and adding a
brand-new Capture slot (the save always has a fixed number of them) -
upstream itself notes the former needs more validation than a plain id
swap, and the latter has no equivalent to inventory's "empty slot" concept
to allocate into.

The two JSON catalogs this module reads (item names/categories, and OT1's
tame-monster names) ship here as real data copied from the upstream
project's static/ folder (data/octopath/*.json) - see that folder's
README.md if they're ever missing or accidentally swapped for a
similarly-named but differently-shaped file. Without them, items/monsters
would just show up as "Unknown item/monster <id>" instead of their real
names, and any item/monster id wouldn't be recognized as writable data
(dumps() validates catalog membership before writing).
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


class SaveError(ValueError):
    pass


CHARACTER_NAMES = {
    1: "Olberic", 2: "Tressa", 3: "Cyrus", 4: "Primrose",
    5: "H'aanit", 6: "Therion", 7: "Ophilia", 8: "Alfyn",
}

EMPTY_U32 = 0xFFFFFFFF

OT2_CHARACTER_NAMES = {
    1: "Hikari", 2: "Agnea", 3: "Partitio", 4: "Osvald",
    5: "Temenos", 6: "Throné", 7: "Castti", 8: "Ochette",
}

OT1_JOB_NAMES = {
    0: "Merchant", 1: "Thief", 2: "Warrior", 3: "Hunter",
    4: "Cleric", 5: "Dancer", 6: "Scholar", 7: "Apothecary",
    8: "Weaponmaster", 9: "Sorcerer", 10: "Starseer", 11: "Runelord",
}

NO_SECOND_JOB = EMPTY_U32

CAPTURE_COUNT_LIMIT = (0, 9_999)  # matches the community editor's own bound
INVENTORY_COUNT_LIMIT = (0, 99)

EQUIPMENT_SLOTS = [
    ("Sword", "Sword"), ("Lance", "Lance"), ("Dagger", "Dagger"), ("Axe", "Axe"),
    ("Bow", "Bow"), ("Rod", "Rod"), ("Shield", "Shield"), ("Head", "Head"),
    ("Body", "Body"), ("Accessory_00", "Accessory 1"), ("Accessory_01", "Accessory 2"),
]
EQUIPMENT_SLOT_KEYS = {slot_key for slot_key, _ in EQUIPMENT_SLOTS}


def equipment_slot_category(slot_key: str) -> str:
    return slot_key.split("_")[0]


FIELD_LIMITS = {
    "money": (0, 9_999_999),
    "hero": (1, 8),
    "level": (1, 99),
    "exp": (0, 9_999_999),
    "raw_hp": (0, 9_999),
    "raw_mp": (0, 9_999),
    "job_points": (0, 99_999),
    "hp_bonus": (0, 9_999),
    "mp_bonus": (0, 9_999),
    "bp_bonus": (0, 9_999),
    "sp_bonus": (0, 9_999),
    "physical_attack_bonus": (0, 9_999),
    "physical_defense_bonus": (0, 9_999),
    "elemental_attack_bonus": (0, 9_999),
    "elemental_defense_bonus": (0, 9_999),
    "accuracy_bonus": (0, 9_999),
    "evasion_bonus": (0, 9_999),
    "critical_bonus": (0, 9_999),
    "speed_bonus": (0, 9_999),
}

CHARACTER_PROPERTIES = {
    "level": "Level_", "exp": "Exp_", "raw_hp": "RawHP_", "raw_mp": "RawMP_",
    "job_points": "JobPoint_", "hp_bonus": "HP_", "mp_bonus": "MP_", "bp_bonus": "BP_",
    "sp_bonus": "SP_", "physical_attack_bonus": "ATK_", "physical_defense_bonus": "DEF_",
    "elemental_attack_bonus": "MATK_", "elemental_defense_bonus": "MDEF_",
    "accuracy_bonus": "ACC_", "evasion_bonus": "EVA_", "critical_bonus": "CON_",
    "speed_bonus": "AGI_",
}

OT2_CHARACTER_PROPERTIES = {
    "level": "Level", "exp": "Exp", "raw_hp": "RawHP", "raw_mp": "RawMP",
    "job_points": "JobPoint", "hp_bonus": "HP", "mp_bonus": "MP", "bp_bonus": "BP",
    "sp_bonus": "SP", "physical_attack_bonus": "ATK", "physical_defense_bonus": "DEF",
    "elemental_attack_bonus": "MATK", "elemental_defense_bonus": "MDEF",
    "accuracy_bonus": "ACC", "evasion_bonus": "EVA", "critical_bonus": "CON",
    "speed_bonus": "AGI",
}

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "octopath"
ITEM_CATALOG_PATH = DATA_DIR / "items.json"
OT2_ITEM_CATALOG_PATH = DATA_DIR / "items-ot2.json"
CAPTURE_MONSTER_CATALOG_PATH = DATA_DIR / "monsters-ot1.json"
CAPTURE_EMPTY_ID = EMPTY_U32


@dataclass(frozen=True)
class OctoGameProfile:
    id: str
    name: str
    character_names: dict
    character_properties: dict
    money_key: str
    character_id_key: str
    item_id_key: str
    item_count_key: str
    temp_backpack_marker: "str | None"
    item_catalog_path: Path
    equipment_suffix: str
    job_first_key: str
    job_second_key: str
    job_names: dict
    capture_catalog_path: "Path | None"
    capture_array_key: str
    capture_enemy_key: str
    capture_count_key: str
    capture_used_key: str


OT1_PROFILE = OctoGameProfile(
    id="ot1", name="Octopath Traveler",
    character_names=CHARACTER_NAMES, character_properties=CHARACTER_PROPERTIES,
    money_key="Money_", character_id_key="CharacterID_", item_id_key="ItemID_",
    item_count_key="Num_", temp_backpack_marker="Temp_PlayerBackpack",
    item_catalog_path=ITEM_CATALOG_PATH, equipment_suffix="_",
    job_first_key="FirstJobID_", job_second_key="SecondJobID_", job_names=OT1_JOB_NAMES,
    capture_catalog_path=CAPTURE_MONSTER_CATALOG_PATH, capture_array_key="TameMonsterData",
    capture_enemy_key="EnemyID_", capture_count_key="Count_", capture_used_key="Used_",
)

OT2_PROFILE = OctoGameProfile(
    id="ot2", name="Octopath Traveler II",
    character_names=OT2_CHARACTER_NAMES, character_properties=OT2_CHARACTER_PROPERTIES,
    money_key="Money", character_id_key="CharacterID", item_id_key="ItemId",
    item_count_key="Num", temp_backpack_marker=None,
    item_catalog_path=OT2_ITEM_CATALOG_PATH, equipment_suffix="",
    job_first_key="FirstJobID", job_second_key="SecondJobID", job_names={},
    capture_catalog_path=None, capture_array_key="TameMonsterData",
    capture_enemy_key="EnemyID", capture_count_key="Count", capture_used_key="Used",
)

GAME_PROFILES = {"ot1": OT1_PROFILE, "ot2": OT2_PROFILE}


@lru_cache(maxsize=None)
def load_item_catalog(path: Path = ITEM_CATALOG_PATH):
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SaveError("The item catalog is missing or invalid") from exc
    return {int(row["id"]): row for row in rows}


@lru_cache(maxsize=None)
def load_monster_catalog(path: Path):
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SaveError("The tame-monster catalog is missing or invalid") from exc
    return {int(row["id"]): row for row in rows}


def detect_game(data) -> OctoGameProfile:
    if len(data) < 1_000 or bytes(data[:4]) != b"GVAS":
        raise SaveError("This is not an Unreal GVAS save")
    if b"KSSaveGameBP_C" not in data[:2_048]:
        raise SaveError("This GVAS file is not an Octopath Traveler save")
    if _find_properties(data, "ItemId"):
        return OT2_PROFILE
    return OT1_PROFILE


@dataclass(frozen=True)
class IntProperty:
    name: str
    key_offset: int
    value_offset: int
    value: int


def sha256(data) -> str:
    return hashlib.sha256(data).hexdigest()


def _u32(data, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise SaveError("Unexpected end of save data")
    return struct.unpack_from("<I", data, offset)[0]


def _property_at(data, key_offset: int) -> IntProperty:
    if key_offset < 4:
        raise SaveError("Invalid property offset")
    key_length = _u32(data, key_offset - 4)
    if not 2 <= key_length <= 512 or key_offset + key_length > len(data):
        raise SaveError("Invalid property name")
    key_bytes = bytes(data[key_offset:key_offset + key_length])
    if not key_bytes.endswith(b"\0"):
        raise SaveError("Property name is not null terminated")
    try:
        name = key_bytes[:-1].decode("ascii")
    except UnicodeDecodeError as exc:
        raise SaveError("Property name is not ASCII") from exc

    cursor = key_offset + key_length
    type_length = _u32(data, cursor)
    if not 2 <= type_length <= 64 or cursor + 4 + type_length > len(data):
        raise SaveError(f"Invalid type for {name}")
    type_name = bytes(data[cursor + 4:cursor + 4 + type_length]).rstrip(b"\0")
    if type_name != b"IntProperty":
        raise SaveError(f"{name} is not an IntProperty")
    value_offset = cursor + 4 + type_length + 9
    return IntProperty(name, key_offset, value_offset, _u32(data, value_offset))


def _find_properties(data, needle: str, start: int = 0, end=None):
    result = []
    raw = needle.encode("ascii")
    limit = len(data) if end is None else min(end, len(data))
    cursor = max(0, start)
    while cursor < limit:
        offset = data.find(raw, cursor, limit)
        if offset < 0:
            break
        try:
            result.append(_property_at(data, offset))
        except SaveError:
            pass
        cursor = offset + 1
    return result


def _first_property(data, needle: str, start: int = 0, end=None) -> IntProperty:
    found = _find_properties(data, needle, start, end)
    if not found:
        raise SaveError(f"Required property {needle!r} was not found")
    return found[0]


def _bool_property_at(data, key_offset: int) -> IntProperty:
    if key_offset < 4:
        raise SaveError("Invalid property offset")
    key_length = _u32(data, key_offset - 4)
    if not 2 <= key_length <= 512 or key_offset + key_length > len(data):
        raise SaveError("Invalid property name")
    key_bytes = bytes(data[key_offset:key_offset + key_length])
    if not key_bytes.endswith(b"\0"):
        raise SaveError("Property name is not null terminated")
    try:
        name = key_bytes[:-1].decode("ascii")
    except UnicodeDecodeError as exc:
        raise SaveError("Property name is not ASCII") from exc

    cursor = key_offset + key_length
    type_length = _u32(data, cursor)
    if not 2 <= type_length <= 64 or cursor + 4 + type_length > len(data):
        raise SaveError(f"Invalid type for {name}")
    type_name = bytes(data[cursor + 4:cursor + 4 + type_length]).rstrip(b"\0")
    if type_name != b"BoolProperty":
        raise SaveError(f"{name} is not a BoolProperty")
    value_offset = cursor + 4 + type_length + 8
    if value_offset >= len(data):
        raise SaveError("Unexpected end of save data")
    return IntProperty(name, key_offset, value_offset, data[value_offset])


def _find_bool_properties(data, needle: str, start: int = 0, end=None):
    result = []
    raw = needle.encode("ascii")
    limit = len(data) if end is None else min(end, len(data))
    cursor = max(0, start)
    while cursor < limit:
        offset = data.find(raw, cursor, limit)
        if offset < 0:
            break
        try:
            result.append(_bool_property_at(data, offset))
        except SaveError:
            pass
        cursor = offset + 1
    return result


def _first_bool_property(data, needle: str, start: int = 0, end=None) -> IntProperty:
    found = _find_bool_properties(data, needle, start, end)
    if not found:
        raise SaveError(f"Required property {needle!r} was not found")
    return found[0]


def _tame_monster_region(data, profile: OctoGameProfile):
    key_offset = data.find(profile.capture_array_key.encode("ascii"))
    if key_offset < 0:
        return None
    key_length = _u32(data, key_offset - 4)
    cursor = key_offset + key_length
    type_length = _u32(data, cursor)
    type_name = bytes(data[cursor + 4:cursor + 4 + type_length]).rstrip(b"\0")
    if type_name != b"ArrayProperty":
        raise SaveError("Unexpected tame-monster capture data layout")
    size_offset = cursor + 4 + type_length
    size = struct.unpack_from("<Q", data, size_offset)[0]
    value_start = size_offset + 8
    value_end = value_start + size
    if value_end > len(data):
        raise SaveError("Tame-monster capture data runs past the end of the save")
    return value_start, value_end


def _tame_monster_records(data, profile: OctoGameProfile):
    region = _tame_monster_region(data, profile)
    if region is None:
        return []
    start, end = region
    enemy_properties = _find_properties(data, profile.capture_enemy_key, start, end)
    records = []
    for index, enemy_prop in enumerate(enemy_properties):
        block_end = enemy_properties[index + 1].key_offset if index + 1 < len(enemy_properties) else end
        count_prop = _first_property(data, profile.capture_count_key, enemy_prop.key_offset, block_end)
        used_prop = _first_bool_property(data, profile.capture_used_key, enemy_prop.key_offset, block_end)
        records.append({
            "id": enemy_prop.value, "id_offset": enemy_prop.value_offset,
            "count": count_prop.value, "count_offset": count_prop.value_offset,
            "used": used_prop.value, "used_offset": used_prop.value_offset,
        })
    return records


def _inventory_records(data, profile: OctoGameProfile):
    end = len(data)
    if profile.temp_backpack_marker:
        end = data.find(profile.temp_backpack_marker.encode("ascii"))
        if end < 0:
            raise SaveError("The live inventory boundary was not found")
    item_properties = _find_properties(data, profile.item_id_key, 0, end)
    if not item_properties:
        raise SaveError("The live inventory contains no item slots")
    records = []
    for index, item_prop in enumerate(item_properties):
        block_end = item_properties[index + 1].key_offset if index + 1 < len(item_properties) else end
        count_prop = _first_property(data, profile.item_count_key, item_prop.key_offset, block_end)
        records.append({
            "id": item_prop.value, "count": count_prop.value,
            "id_offset": item_prop.value_offset, "count_offset": count_prop.value_offset,
        })
    return records


def parse_save(data, profile: "OctoGameProfile | None" = None) -> dict:
    """Parse a full Octopath Traveler / Octopath Traveler II GVAS save into
    a plain nested dict: money, starting traveler, all 8 characters (core
    stats, stat bonuses, jobs, equipment), inventory, and (OT1) the
    tame-monster Capture roster. Offset bookkeeping needed to write core
    stats back (see games/octopath.py) is kept in "_offsets" keys."""
    if profile is None:
        profile = detect_game(data)

    money = _first_property(data, profile.money_key)
    hero = _first_property(data, "FirstSelectCharacterID")
    character_ids = _find_properties(data, profile.character_id_key)
    characters = []
    catalog = load_item_catalog(profile.item_catalog_path)

    for index, id_prop in enumerate(character_ids):
        character_id = id_prop.value
        if character_id not in profile.character_names:
            continue
        block_end = character_ids[index + 1].key_offset if index + 1 < len(character_ids) else min(id_prop.key_offset + 7_000, len(data))
        row = {"id": character_id, "name": profile.character_names[character_id], "_offsets": {}}
        for field, property_name in profile.character_properties.items():
            prop = _first_property(data, property_name, id_prop.key_offset, block_end)
            row[field] = prop.value
            row["_offsets"][field] = prop.value_offset

        first_job = _first_property(data, profile.job_first_key, id_prop.key_offset, block_end)
        row["first_job_id"] = first_job.value
        row["first_job_name"] = profile.job_names.get(first_job.value)
        try:
            second_job = _first_property(data, profile.job_second_key, id_prop.key_offset, block_end)
            row["second_job_id"] = second_job.value if second_job.value != NO_SECOND_JOB else None
            row["second_job_name"] = profile.job_names.get(second_job.value)
            row["_offsets"]["second_job_id"] = second_job.value_offset
        except SaveError:
            row["second_job_id"] = None
            row["second_job_name"] = None

        equipment = []
        for slot_key, slot_label in EQUIPMENT_SLOTS:
            try:
                slot = _first_property(data, f"{slot_key}{profile.equipment_suffix}", id_prop.key_offset, block_end)
            except SaveError:
                continue
            is_empty = slot.value in (0, 0xFFFFFFFF)
            info = catalog.get(slot.value, {}) if not is_empty else {}
            equipment.append({
                "slot": slot_label, "slot_key": slot_key, "category": equipment_slot_category(slot_key),
                "id": None if is_empty else slot.value,
                "name": None if is_empty else info.get("name", f"Unknown item {slot.value}"),
                "_offset": slot.value_offset,
            })
        row["equipment"] = equipment
        characters.append(row)

    if len(characters) != 8:
        raise SaveError(f"Expected 8 traveler records, found {len(characters)}")

    capture_slots = []
    if profile.capture_catalog_path is not None:
        monster_catalog = load_monster_catalog(profile.capture_catalog_path)
        for index, record in enumerate(_tame_monster_records(data, profile)):
            monster_id = record["id"]
            is_empty = monster_id == CAPTURE_EMPTY_ID
            info = monster_catalog.get(monster_id) if not is_empty else None
            capture_slots.append({
                "index": index, "id": None if is_empty else monster_id,
                "name": None if is_empty else info["name"] if info else f"Unknown monster {monster_id}",
                "types": info.get("types", []) if info else [],
                "strength": info.get("strength") if info else None,
                "skills": info.get("skills", []) if info else [],
                "special": info.get("special") if info else None,
                "count": record["count"], "used": bool(record["used"]),
                "_offsets": {"id": record["id_offset"], "count": record["count_offset"], "used": record["used_offset"]},
            })

    inventory_records = _inventory_records(data, profile)
    inventory = []
    inventory_slots = {}
    empty_slots = []
    for record in inventory_records:
        item_id = record["id"]
        if item_id == 0:
            empty_slots.append(record)
            continue
        if item_id in inventory_slots:
            raise SaveError(f"Duplicate item ID {item_id} in the live inventory")
        inventory_slots[item_id] = record
        info = catalog.get(item_id, {})
        inventory.append({
            "id": item_id, "name": info.get("name", f"Unknown item {item_id}"),
            "category": info.get("category", "Unknown"), "editable": bool(info.get("editable", False)),
            "count": record["count"],
        })
    inventory.sort(key=lambda row: (row["category"], row["name"], row["id"]))

    return {
        "format": "GVAS / Unreal Engine 4.27",
        "game": profile.id,
        "game_name": profile.name,
        "size": len(data),
        "sha256": sha256(data),
        "money": money.value,
        "hero": hero.value,
        "hero_name": profile.character_names.get(hero.value, "Unknown"),
        "characters": characters,
        "capture": {"available": profile.capture_catalog_path is not None, "slots": capture_slots},
        "inventory": inventory,
        "inventory_capacity": len(inventory_records),
        "inventory_empty_slots": len(empty_slots),
        "_offsets": {"money": money.value_offset, "hero": hero.value_offset},
        # Bookkeeping for games/octopath.py's writer, same idea as each
        # character row's own "_offsets": item_id -> its slot's raw
        # id_offset/count_offset (existing items), and the still-empty
        # slots' own offsets (for writing a brand new item into the live
        # inventory) - never trusted at face value, dumps() always
        # re-derives these fresh from the pristine save bytes rather than
        # carrying them forward from a possibly-stale parse.
        "_inventory_slots": inventory_slots,
        "_inventory_empty": empty_slots,
    }
