"""
cedit game profile: Octopath Traveler / Octopath Traveler II

Save format: GVAS (Unreal Engine 4.27's SaveGame binary layout), the same
for both games (save class "KSSaveGameBP_C"); which one a given file is
gets auto-detected from its contents (lib/octopath_lib.py: detect_game).

This is fundamentally different from Duckov's plain-JSON saves, so unlike
games/duckov.py this profile is NOT config-driven - GameProfile.binary=True
and custom loads/dumps are exactly the "genuinely unusual format" escape
hatch the lib/base.py module docstring describes.

Parsing (browsing) vs. writing (editing) have deliberately different scope
here:

  - Parsing (lib/octopath_lib.py, adapted from AppleBoiy/octopath-save-
    editor, GPL-3.0) reads the WHOLE save: money, starting traveler, all 8
    characters' stats/bonuses/jobs/equipment, full inventory, and (OT1) the
    tame-monster Capture roster. All of it is browsable in cedit's tree.

  - Writing covers every field that's a simple fixed-offset scalar
    overwrite with no structural side effects: money, the starting
    traveler, each character's core stats/stat bonuses, which item
    occupies an equipment slot, an existing inventory item's count (plus
    adding a brand-new item into one of the save's already-allocated but
    currently-empty inventory slots), and (OT1) each Capture slot's
    monster id/count/used flag. This mirrors the upstream project's own
    normalize_edits/apply_edits validation (item/monster catalog
    membership, equipment category matching, count bounds, empty-slot
    allocation for a new inventory item), ported here to work against
    cedit's "mutate the parsed dict, then dumps() reconciles it against a
    fresh pristine reparse" editing model instead of upstream's
    key-path edits dict.

    Left out deliberately: second job assignment (upstream itself notes
    this needs more validation than a plain id swap), and adding a
    brand-new Capture slot (the save always has a fixed number of slots;
    only editing an existing one's contents is supported, same as
    inventory only ever reuses slots the save already allocated).

  read_only_check() below is what enforces that split: it blocks every
  field outside the writable set from being edited in the tree at all,
  rather than silently discarding an edit the "Save" step doesn't know
  how to write back.

Every write re-parses the ORIGINAL pristine bytes fresh (never trusting
whatever bookkeeping the in-memory parsed dict happens to be carrying) to
get real slot offsets and "before" values to diff against, then re-parses
the newly patched bytes and checks every intended change actually reads
back correctly before returning it - mirroring the upstream project's own
verify-before-write discipline (see dumps() below).
"""

import os
import struct

from lib.base import GameProfile
from lib import octopath_lib as octo_lib


DEFAULT_SAVE_DIRS = [
    "~/Documents/My Games/Octopath_Traveler",
    "~/Documents/My Games/Octopath_Traveler2",
    "~/Documents/My Games/Octopath_Traveler/Steam",
    "~/Documents/My Games/Octopath_Traveler2/Steam",
    "~/OneDrive/Documents/My Games/Octopath_Traveler",
    "~/OneDrive/Documents/My Games/Octopath_Traveler2",
]


class OctopathData(dict):
    """The parsed save (games/octopath_lib.parse_save output), plus the
    original file bytes needed to patch edits back in (kept as a plain
    instance attribute so it doesn't show up as a dict key/tree node)."""
    pass


def loads(raw_bytes):
    data = octo_lib.parse_save(raw_bytes)
    wrapped = OctopathData(data)
    wrapped._raw = bytes(raw_bytes)
    return wrapped


# Character fields safe to write back: exactly the stat/bonus fields
# lib/octopath_lib.parse_save records a fixed offset for. Job IDs have
# offsets too, but are excluded here (see module docstring).
_EDITABLE_CHARACTER_FIELDS = frozenset(octo_lib.CHARACTER_PROPERTIES.keys())
_EDITABLE_ROOT_FIELDS = frozenset({"money", "hero"})
_EDITABLE_CAPTURE_FIELDS = frozenset({"id", "count", "used"})


def _looks_like_root(container):
    return (
        isinstance(container, dict)
        and "money" in container and "hero" in container and "characters" in container
    )


def _looks_like_character_row(container):
    return (
        isinstance(container, dict)
        and "id" in container and "name" in container
        and "level" in container and "equipment" in container
    )


def _looks_like_equipment_slot(container):
    return (
        isinstance(container, dict)
        and "slot_key" in container and "category" in container and "_offset" in container
    )


def _looks_like_inventory_item(container):
    return (
        isinstance(container, dict)
        and "editable" in container and "count" in container
        and "category" in container and "id" in container
    )


def _looks_like_capture_slot(container):
    return (
        isinstance(container, dict)
        and "used" in container and "strength" in container and "_offsets" in container
    )


def read_only_check(container, key, value):
    if isinstance(key, str) and key.startswith("_"):
        return True  # offset bookkeeping and other internals
    if _looks_like_root(container):
        return key not in _EDITABLE_ROOT_FIELDS
    if _looks_like_character_row(container):
        return key not in _EDITABLE_CHARACTER_FIELDS
    if _looks_like_equipment_slot(container):
        return key != "id"
    if _looks_like_inventory_item(container):
        if key != "count":
            return True
        # Matches the upstream editor's own rule: only items whose catalog
        # entry is flagged "editable" (ordinary consumables/equipment, not
        # progression-linked key items) can have their count changed.
        return not bool(container.get("editable", False))
    if _looks_like_capture_slot(container):
        return key not in _EDITABLE_CAPTURE_FIELDS
    # Job names, slot labels, sprite paths, etc: fully browsable, never writable.
    return True


def _check_bounds(field, value):
    limits = octo_lib.FIELD_LIMITS.get(field)
    if limits is None:
        return
    lo, hi = limits
    if not lo <= value <= hi:
        raise ValueError(f"{field} must be between {lo:,} and {hi:,} (got {value:,})")


def dumps(data):
    if not isinstance(data, OctopathData) or not hasattr(data, "_raw"):
        raise ValueError(
            "This save wasn't loaded through cedit's Octopath profile (missing "
            "original file bytes) - reload the file and try again."
        )

    game_profile = octo_lib.GAME_PROFILES[data["game"]]
    catalog = octo_lib.load_item_catalog(game_profile.item_catalog_path)
    # A fresh, pristine reparse of the ORIGINAL bytes - the single source of
    # truth for every offset and "before" value below. Never derived from
    # the in-memory `data` dict, which the user (or a raw-JSON paste) may
    # have mutated in ways that don't correspond to real save layout.
    before = octo_lib.parse_save(data._raw, game_profile)
    raw = bytearray(data._raw)

    # --- money / starting traveler ---
    money = int(data["money"])
    hero = int(data["hero"])
    _check_bounds("money", money)
    _check_bounds("hero", hero)
    struct.pack_into("<I", raw, before["_offsets"]["money"], money)
    struct.pack_into("<I", raw, before["_offsets"]["hero"], hero)

    # --- character stats/bonuses + equipment ---
    before_chars = {row["id"]: row for row in before["characters"]}
    for row in data["characters"]:
        before_row = before_chars.get(row["id"])
        if before_row is None:
            continue  # traveler id changed out from under us - nothing safe to write for it

        for field, offset in before_row["_offsets"].items():
            if field == "second_job_id" or field not in _EDITABLE_CHARACTER_FIELDS:
                continue  # not writable in cedit - never repacked
            value = row.get(field)
            if value is None:
                continue
            value = int(value)
            _check_bounds(field, value)
            struct.pack_into("<I", raw, offset, value)

        before_equipment = {slot["slot_key"]: slot for slot in before_row["equipment"]}
        for slot in row.get("equipment", []):
            slot_key = slot.get("slot_key")
            before_slot = before_equipment.get(slot_key)
            if before_slot is None:
                continue
            new_id = slot.get("id")
            new_value = octo_lib.EMPTY_U32 if new_id in (None, 0) else int(new_id)
            old_value = octo_lib.EMPTY_U32 if before_slot["id"] is None else before_slot["id"]
            if new_value == old_value:
                continue
            if new_value != octo_lib.EMPTY_U32:
                item = catalog.get(new_value)
                if item is None:
                    raise ValueError(f"Unknown item ID {new_value} for {slot.get('slot', slot_key)}")
                expected_category = octo_lib.equipment_slot_category(slot_key)
                if item.get("category") != expected_category:
                    raise ValueError(
                        f"{item['name']} cannot be equipped in the {expected_category} slot"
                    )
            struct.pack_into("<I", raw, before_slot["_offset"], new_value)

    # --- inventory: existing item counts, plus a new item into an empty slot ---
    before_inventory_by_id = {row["id"]: row for row in before["inventory"]}
    before_slots = dict(before["_inventory_slots"])
    empty_slots = list(before["_inventory_empty"])
    inv_lo, inv_hi = octo_lib.INVENTORY_COUNT_LIMIT
    for row in data.get("inventory", []):
        item_id = row.get("id")
        count = row.get("count")
        if item_id is None or count is None:
            continue
        item_id = int(item_id)
        count = int(count)
        old_count = before_inventory_by_id.get(item_id, {}).get("count", 0)
        if count == old_count:
            continue
        item = catalog.get(item_id)
        if item is None:
            raise ValueError(f"Unknown item ID {item_id} in inventory")
        if not item.get("editable", False):
            raise ValueError(f"{item['name']} is progression-linked and read-only")
        if not (inv_lo <= count <= inv_hi):
            raise ValueError(f"{item['name']} count must be between {inv_lo} and {inv_hi}")
        slot = before_slots.get(item_id)
        if slot is None:
            if count == 0:
                continue  # "new" item with count 0 is a no-op
            if not empty_slots:
                raise ValueError(f"No empty inventory slot available to add {item['name']}")
            slot = empty_slots.pop(0)
            struct.pack_into("<I", raw, slot["id_offset"], item_id)
        elif count == 0:
            struct.pack_into("<I", raw, slot["id_offset"], 0)
        struct.pack_into("<I", raw, slot["count_offset"], count)

    # --- (OT1) Capture roster ---
    if game_profile.capture_catalog_path is not None:
        monster_catalog = octo_lib.load_monster_catalog(game_profile.capture_catalog_path)
        before_capture_by_index = {slot["index"]: slot for slot in before["capture"]["slots"]}
        cap_lo, cap_hi = octo_lib.CAPTURE_COUNT_LIMIT
        for slot in data.get("capture", {}).get("slots", []):
            index = slot.get("index")
            before_slot = before_capture_by_index.get(index)
            if before_slot is None:
                continue
            offsets = before_slot["_offsets"]

            new_id = slot.get("id")
            id_value = octo_lib.CAPTURE_EMPTY_ID if new_id is None else int(new_id)
            old_id_value = octo_lib.CAPTURE_EMPTY_ID if before_slot["id"] is None else before_slot["id"]
            if id_value != old_id_value:
                if id_value != octo_lib.CAPTURE_EMPTY_ID and id_value not in monster_catalog:
                    raise ValueError(f"Unknown monster ID {id_value}")
                struct.pack_into("<I", raw, offsets["id"], id_value)

            new_count = slot.get("count")
            if new_count is not None and int(new_count) != before_slot["count"]:
                count_value = int(new_count)
                if not (cap_lo <= count_value <= cap_hi):
                    raise ValueError(f"Capture slot {index + 1} count must be between {cap_lo:,} and {cap_hi:,}")
                struct.pack_into("<I", raw, offsets["count"], count_value)

            new_used = slot.get("used")
            if new_used is not None and bool(new_used) != before_slot["used"]:
                raw[offsets["used"]] = 1 if new_used else 0

    new_bytes = bytes(raw)

    # Verify before handing back: re-parse the patched bytes and confirm
    # every field we just wrote reads back exactly as intended.
    try:
        verify = octo_lib.parse_save(new_bytes)
    except octo_lib.SaveError as e:
        raise ValueError(f"Post-write verification failed to parse the result: {e}")

    if verify["money"] != money:
        raise ValueError("Post-write verification failed for money")
    if verify["hero"] != hero:
        raise ValueError("Post-write verification failed for the starting traveler")

    verify_by_id = {row["id"]: row for row in verify["characters"]}
    for row in data["characters"]:
        vrow = verify_by_id.get(row["id"])
        for field in before_chars.get(row["id"], {}).get("_offsets", {}):
            if field == "second_job_id" or field not in _EDITABLE_CHARACTER_FIELDS:
                continue
            expected = row.get(field)
            if expected is None:
                continue
            if vrow is None or vrow.get(field) != int(expected):
                raise ValueError(f"Post-write verification failed for {row['name']} - {field}")

        v_equipment = {s["slot_key"]: s for s in vrow["equipment"]} if vrow else {}
        for slot in row.get("equipment", []):
            slot_key = slot.get("slot_key")
            expected_id = slot.get("id")
            expected_value = octo_lib.EMPTY_U32 if expected_id in (None, 0) else int(expected_id)
            vslot = v_equipment.get(slot_key)
            actual_value = octo_lib.EMPTY_U32 if (vslot is None or vslot["id"] is None) else vslot["id"]
            if actual_value != expected_value:
                raise ValueError(
                    f"Post-write verification failed for {row['name']} - {slot.get('slot', slot_key)}"
                )

    verify_inventory_by_id = {row["id"]: row for row in verify["inventory"]}
    for row in data.get("inventory", []):
        item_id, count = row.get("id"), row.get("count")
        if item_id is None or count is None:
            continue
        expected = int(count)
        actual = verify_inventory_by_id.get(int(item_id), {}).get("count", 0)
        if actual != expected:
            raise ValueError(f"Post-write verification failed for inventory item {item_id}")

    if game_profile.capture_catalog_path is not None:
        v_capture_by_index = {s["index"]: s for s in verify["capture"]["slots"]}
        for slot in data.get("capture", {}).get("slots", []):
            index = slot.get("index")
            vslot = v_capture_by_index.get(index)
            if vslot is None:
                continue
            expected_id = slot.get("id")
            expected_id_value = octo_lib.CAPTURE_EMPTY_ID if expected_id is None else int(expected_id)
            actual_id_value = octo_lib.CAPTURE_EMPTY_ID if vslot["id"] is None else vslot["id"]
            if actual_id_value != expected_id_value:
                raise ValueError(f"Post-write verification failed for capture slot {index + 1}")
            if slot.get("count") is not None and vslot["count"] != int(slot["count"]):
                raise ValueError(f"Post-write verification failed for capture slot {index + 1} count")
            if slot.get("used") is not None and vslot["used"] != bool(slot["used"]):
                raise ValueError(f"Post-write verification failed for capture slot {index + 1} used flag")

    return new_bytes


PROFILE = GameProfile(
    key="octopath",
    display_name="Octopath Traveler / II",
    default_save_dirs=[os.path.expanduser(p) for p in DEFAULT_SAVE_DIRS],
    file_patterns=[("Octopath save files", "*.sav"), ("All files", "*.*")],
    quick_fields={
        "Money": ["money"],
        "Starting Traveler (1-8)": ["hero"],
    },
    loads=loads,
    dumps=dumps,
    binary=True,
    read_only_check=read_only_check,
    notes=(
        "Auto-detects Octopath Traveler vs. Octopath Traveler II from the save "
        "itself. Editable: money, starting traveler, each character's "
        "level/EXP/HP/MP/job points/stat bonuses, which item occupies an "
        "equipment slot, an inventory item's count (only for items the catalog "
        "marks non-progression-linked - also works to add a new item into any "
        "still-empty inventory slot), and (OT1) each Capture slot's monster/"
        "count/caught flag. Second-job assignment and adding brand-new Capture "
        "slots are not supported.\n"
        "Item/monster names show as 'Unknown item/monster <id>' until the real "
        "catalogs from the upstream project's static/ folder are dropped into "
        "data/octopath/ (see the README.md there)."
    ),
)
