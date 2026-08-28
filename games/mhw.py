"""
cedit game profile: Monster Hunter World: Iceborne (PC, SAVEDATA1000)

The crypto (two encryption layers - see lib/mhw_crypto.py's own docstring)
was ported straight from EnderHDMC/MHWISaveEditor's real C++ source and
verified byte-for-byte round-trip against a real save file (re-encrypting
an unedited decrypt reproduces the original file exactly).

The struct LAYOUT below (byte offsets for the hunter/item-pouch/storage/
equipment fields this profile edits) comes from that same project's own
SAVEDATA1000.bt (a 010 Editor binary template, hand-maintained by the
project's authors) - except the three save-slot regions' absolute file
offsets/lengths, which come from iceborne_crypt.h's own DecryptSave/
EncryptSave calls instead (lib.mhw_crypto.SLOT_REGIONS): the .bt's
computed section layout is off by ~1KB from where the actual encrypted
regions start (probably template drift against a slightly newer patch),
so it's only trustworthy for offsets *relative to* a slot's own start,
never for locating that start within the file.

Rather than parse the entire multi-megabyte, mostly-still-unmapped
per-slot struct into a Python object and re-serialize the whole thing
back (most of it is undocumented and would be too easy to corrupt),
loads() keeps the full decrypted buffer around (MHWSaveData.raw) and
only decodes the specific fields this profile knows about into a normal
nested dict/list Python structure for cedit's tree editor. dumps() then
writes just those same fields back into their exact original byte
offsets in that buffer and re-encrypts - anything this profile doesn't
understand yet (equipment sub-fields like decorations/augments, guild
cards, quest completion, room decor, investigations, ...) round-trips
untouched because its bytes were never touched at all.
"""
import json
import struct
from pathlib import Path

from lib.base import GameProfile
from lib.mhw_crypto import SLOT_REGIONS, decrypt_save, encrypt_save

# data/mhw/item_names.json: itemID -> display name, covering items, ammo,
# materials, and decorations (they all share one ID space in MHW's own
# itemData.itm table - equipment/weapon/armor ids are a separate namespace
# this catalog doesn't cover). Extracted straight from the game's own
# shipped itemData.itm + item_eng.gmd files (bundled inside the
# MHWISaveEditor-master repo the user pointed cedit at) - see
# data/mhw/README.md for exactly how, and data/mhw/extract_item_names.py
# for the extraction script itself. Loaded once at import time; missing/
# corrupt just means no names show, not a crash - same convention as
# games/duckov.py's own catalog.
_ITEM_NAMES_PATH = Path(__file__).resolve().parent.parent / "data" / "mhw" / "item_names.json"
try:
    _ITEM_NAMES = json.loads(_ITEM_NAMES_PATH.read_text(encoding="utf-8"))
except (FileNotFoundError, json.JSONDecodeError):
    _ITEM_NAMES = {}


def item_name(item_id):
    """itemID (int or str) -> looked-up display name, or None if this
    catalog doesn't cover it (id 0 = empty slot, or an id outside the
    2774-entry table this was extracted from)."""
    return _ITEM_NAMES.get(str(item_id))


def _describe_entry(container, key, value):
    if key == "id" and isinstance(value, int) and isinstance(container, dict):
        if "amount" in container:
            # An item_pouch/storage slot dict ({"id", "amount"}).
            return item_name(value)
        if "category" in container and "type" in container:
            # An equipment entry ({"category", "type", "id", ...}) - a
            # completely different id space from item_name's, keyed on
            # (category, type, id) together, not id alone.
            return equipment_name(container["category"], container["type"], value)
    return None


def item_catalog(data):
    """Every catalog entry, as [(name, id_str), ...] sorted by name - feeds
    the Inventory Editor window's "Browse Catalog..." picker, and the
    dedicated MHW editor window's own item pickers."""
    return sorted(((name, item_id) for item_id, name in _ITEM_NAMES.items()), key=lambda row: row[0].lower())


# data/mhw/equipment_names.json: "category:type:id" -> display name (armor,
# charms, and the 13 weapon trees - see data/mhw/README.md's "Equipment"
# section for how, and extract_equipment_names.py for the script). This is
# a SEPARATE id space from _ITEM_NAMES above: an equipment entry's own
# "id" field only means something alongside its "category"/"type" fields,
# unlike item pouch/storage slots where a bare id is already unambiguous.
# Kinsects aren't covered - rod_insect.rod_inse isn't the plain packed
# struct every other equipment file here is (looks compressed/encrypted;
# left unparsed rather than guessed at), so kinsect equipment entries still
# only show a raw id.
_EQUIPMENT_NAMES_PATH = Path(__file__).resolve().parent.parent / "data" / "mhw" / "equipment_names.json"
try:
    _EQUIPMENT_NAMES = json.loads(_EQUIPMENT_NAMES_PATH.read_text(encoding="utf-8"))
except (FileNotFoundError, json.JSONDecodeError):
    _EQUIPMENT_NAMES = {}

# mhw_equip_category (types/mhw_enums.h) - only the categories this
# catalog actually covers.
EQUIP_CATEGORY_ARMOR = 0
EQUIP_CATEGORY_WEAPON = 1
EQUIP_CATEGORY_CHARM = 2
EQUIP_CATEGORY_KINSECT = 4
EQUIP_CATEGORY_NAMES = {
    -1: "(empty)", 0: "Armor", 1: "Weapon", 2: "Charm", 3: "Tool", 4: "Kinsect",
}
# Weapon "type" values (mhw_equip_type, weapon half) - EquipmentDB's own
# BindMapping order. Armor's "type" values (Helmet=0..Feet=4) reuse the
# same enum at different numbers and don't need a separate label table -
# the equipment tab just shows the raw slot number for those.
WEAPON_TYPE_NAMES = {
    0: "Great Sword", 1: "Sword And Shield", 2: "Dual Blades", 3: "Longsword",
    4: "Hammer", 5: "Hunting Horn", 6: "Lance", 7: "Gunlance", 8: "Switch Axe",
    9: "Charge Blade", 10: "Insect Glaive", 11: "Bow", 12: "Heavy Bowgun",
    13: "Light Bowgun",
}


def equipment_name(category, equip_type, item_id):
    """(category, type, id) -> looked-up display name, or None if this
    catalog doesn't cover it (kinsects, category "Tool", or an id this
    extraction didn't find - see this module's own catalog docstring)."""
    return _EQUIPMENT_NAMES.get(f"{category}:{equip_type}:{item_id}")


def equipment_catalog():
    """Every known (category, type, id) triple as
    [(display_name, "category:type:id"), ...] sorted by name - feeds the
    dedicated MHW editor window's equipment picker."""
    return sorted(
        ((name, key) for key, name in _EQUIPMENT_NAMES.items()),
        key=lambda row: row[0].lower(),
    )

# ------------------------------------------------------- per-slot layout
#
# Byte offsets are relative to a save slot's own start (SLOT_REGIONS[n][0]
# in the fully-decrypted buffer) - see this module's docstring for why
# that start itself has to come from lib.mhw_crypto, not the .bt.

_HUNTER_OFF = 4          # u32 unknown0, then mhw_hunter
_HUNTER_FMT = "<64s8I"   # name, hunter_rank, master_rank, zeni, research_points,
                         # hunter_rank_xp, master_rank_xp, playtime, room_preference
_HUNTER_SIZE = struct.calcsize(_HUNTER_FMT)  # 96

_ITEM_POUCH_OFF = 1_138_840
_ITEM_POUCH_ITEMS = 24
_ITEM_POUCH_AMMO = 16

_STORAGE_OFF = 1_139_456
_STORAGE_ITEMS = 200
_STORAGE_AMMO = 200
_STORAGE_MATERIALS = 1250
_STORAGE_DECORATIONS = 500

_ITEM_SLOT_FMT = "<2I"   # id, amount
_ITEM_SLOT_SIZE = struct.calcsize(_ITEM_SLOT_FMT)  # 8

_EQUIPMENT_OFF = 1_156_656
_EQUIPMENT_COUNT = 2500
# sort_index, category, type, id, level, points, deco0-2, pendant - the
# gameplay-relevant scalar fields; bowgun_mods/augments/custom_upgrades/
# awakens aren't exposed yet (still preserved byte-for-byte on save).
_EQUIPMENT_FMT = "<3i3I3ii"
_EQUIPMENT_SIZE = 125  # real struct size (see games/mhw.py's own notes below);
                        # _EQUIPMENT_FMT only covers this struct's first 40 bytes


# --------------------------------------------------------------- loads/dumps

class MHWSaveData(dict):
    """A plain dict (so cedit.py's generic get_by_path/set_by_path tree
    editing works on it unmodified) that also carries the full decrypted
    save buffer around as a hidden, non-key attribute - dumps() patches
    edited fields back into this buffer rather than trying to serialize
    the whole (mostly still unmapped) save structure from scratch."""


def _unpack_hunter(raw, slot_off):
    name, hr, mr, zeni, rp, hrxp, mrxp, playtime, room = struct.unpack_from(
        _HUNTER_FMT, raw, slot_off + _HUNTER_OFF
    )
    return {
        "name": name.split(b"\x00", 1)[0].decode("utf-8", errors="replace"),
        "hunter_rank": hr,
        "master_rank": mr,
        "zeni": zeni,
        "research_points": rp,
        "hunter_rank_xp": hrxp,
        "master_rank_xp": mrxp,
        "playtime_seconds": playtime,
        "room_preference": room,
    }


def _pack_hunter(raw, slot_off, hunter):
    name_bytes = hunter["name"].encode("utf-8", errors="replace")[:63]
    name_bytes = name_bytes + b"\x00" * (64 - len(name_bytes))
    struct.pack_into(
        _HUNTER_FMT, raw, slot_off + _HUNTER_OFF,
        name_bytes,
        int(hunter["hunter_rank"]), int(hunter["master_rank"]), int(hunter["zeni"]),
        int(hunter["research_points"]), int(hunter["hunter_rank_xp"]),
        int(hunter["master_rank_xp"]), int(hunter["playtime_seconds"]),
        int(hunter["room_preference"]),
    )


def _unpack_slots(raw, off, count):
    return [
        {"id": v[0], "amount": v[1]}
        for v in struct.iter_unpack(_ITEM_SLOT_FMT, bytes(raw[off:off + count * _ITEM_SLOT_SIZE]))
    ]


def _pack_slots(raw, off, slots):
    for i, entry in enumerate(slots):
        struct.pack_into(_ITEM_SLOT_FMT, raw, off + i * _ITEM_SLOT_SIZE,
                          int(entry["id"]), int(entry["amount"]))


def _unpack_item_pouch(raw, slot_off):
    base = slot_off + _ITEM_POUCH_OFF
    return {
        "items": _unpack_slots(raw, base, _ITEM_POUCH_ITEMS),
        "ammo": _unpack_slots(raw, base + _ITEM_POUCH_ITEMS * _ITEM_SLOT_SIZE, _ITEM_POUCH_AMMO),
    }


def _pack_item_pouch(raw, slot_off, pouch):
    base = slot_off + _ITEM_POUCH_OFF
    _pack_slots(raw, base, pouch["items"])
    _pack_slots(raw, base + _ITEM_POUCH_ITEMS * _ITEM_SLOT_SIZE, pouch["ammo"])


def _unpack_storage(raw, slot_off):
    base = slot_off + _STORAGE_OFF
    off = base
    out = {}
    for name, count in (("items", _STORAGE_ITEMS), ("ammo", _STORAGE_AMMO),
                         ("materials", _STORAGE_MATERIALS), ("decorations", _STORAGE_DECORATIONS)):
        out[name] = _unpack_slots(raw, off, count)
        off += count * _ITEM_SLOT_SIZE
    return out


def _pack_storage(raw, slot_off, storage):
    base = slot_off + _STORAGE_OFF
    off = base
    for name, count in (("items", _STORAGE_ITEMS), ("ammo", _STORAGE_AMMO),
                         ("materials", _STORAGE_MATERIALS), ("decorations", _STORAGE_DECORATIONS)):
        _pack_slots(raw, off, storage[name])
        off += count * _ITEM_SLOT_SIZE


def _unpack_equipment(raw, slot_off):
    base = slot_off + _EQUIPMENT_OFF
    out = []
    for i in range(_EQUIPMENT_COUNT):
        entry_off = base + i * _EQUIPMENT_SIZE
        sort_index, category, etype, item_id, level, points, d0, d1, d2, pendant = \
            struct.unpack_from(_EQUIPMENT_FMT, raw, entry_off)
        out.append({
            "sort_index": sort_index, "category": category, "type": etype,
            "id": item_id, "level": level, "points": points,
            "decos": [d0, d1, d2], "pendant": pendant,
        })
    return out


def _pack_equipment(raw, slot_off, equipment):
    base = slot_off + _EQUIPMENT_OFF
    for i, e in enumerate(equipment):
        entry_off = base + i * _EQUIPMENT_SIZE
        decos = e["decos"]
        struct.pack_into(
            _EQUIPMENT_FMT, raw, entry_off,
            int(e["sort_index"]), int(e["category"]), int(e["type"]),
            int(e["id"]), int(e["level"]), int(e["points"]),
            int(decos[0]), int(decos[1]), int(decos[2]), int(e["pendant"]),
        )


def loads(raw_bytes):
    raw, region_ok = decrypt_save(raw_bytes)
    bad = [slot for slot, ok in region_ok.items() if not ok]
    if bad:
        raise ValueError(
            f"Save decrypted, but the checksum for slot(s) {bad} didn't match - "
            f"that slot's data may be corrupt. Loading anyway so the other "
            f"slot(s) are still usable; be cautious editing/saving the flagged one."
        )

    data = MHWSaveData()
    data.raw = raw
    data["slots"] = []
    for slot in (0, 1, 2):
        slot_off, _length = SLOT_REGIONS[slot]
        data["slots"].append({
            "hunter": _unpack_hunter(raw, slot_off),
            "item_pouch": _unpack_item_pouch(raw, slot_off),
            "storage": _unpack_storage(raw, slot_off),
            "equipment": _unpack_equipment(raw, slot_off),
        })
    return data


def dumps(data):
    if not isinstance(data, MHWSaveData) or not hasattr(data, "raw"):
        raise TypeError("This isn't a save loaded by games/mhw.py's own loads().")
    raw = bytearray(data.raw)
    for slot in (0, 1, 2):
        slot_off, _length = SLOT_REGIONS[slot]
        entry = data["slots"][slot]
        _pack_hunter(raw, slot_off, entry["hunter"])
        _pack_item_pouch(raw, slot_off, entry["item_pouch"])
        _pack_storage(raw, slot_off, entry["storage"])
        _pack_equipment(raw, slot_off, entry["equipment"])
    return encrypt_save(raw)


# ------------------------------------------------------- inventory editor
#
# Target keys are "<slot>:<container>", e.g. "0:item_pouch:items" - the
# Inventory Editor window treats each as an independent fixed-size grid
# (unlike Duckov, MHW's pouch/storage arrays have a fixed slot count with
# no separate capacity concept - every array index always "exists", just
# possibly holding id=0/amount=0 for "empty").

_CONTAINER_LABELS = [
    ("Item Pouch - Items", "item_pouch:items"),
    ("Item Pouch - Ammo", "item_pouch:ammo"),
    ("Storage - Items", "storage:items"),
    ("Storage - Ammo", "storage:ammo"),
    ("Storage - Materials", "storage:materials"),
    ("Storage - Decorations", "storage:decorations"),
]


def spawn_item_targets(data):
    targets = []
    for slot_idx, slot in enumerate(data["slots"]):
        name = slot["hunter"]["name"] or f"Slot {slot_idx + 1}"
        for label, key in _CONTAINER_LABELS:
            targets.append((f"{name} - {label}", f"{slot_idx}:{key}"))
    return targets


def _resolve_container(data, target_key):
    try:
        slot_str, section, container = target_key.split(":")
        slot_idx = int(slot_str)
    except ValueError:
        raise ValueError(f"Unknown inventory target {target_key!r}.")
    try:
        slot = data["slots"][slot_idx]
    except (IndexError, TypeError):
        raise ValueError(f"No such save slot {slot_str!r}.")
    section_data = slot.get(section)
    if not isinstance(section_data, dict) or container not in section_data:
        raise ValueError(f"Unknown inventory target {target_key!r}.")
    return section_data[container]


def inventory_state(data, target_key):
    slots = _resolve_container(data, target_key)
    occupied = [
        {"position": i, "instance_id": i, "type_id": entry["id"]}
        for i, entry in enumerate(slots) if entry["id"] != 0
    ]
    return {"capacity": len(slots), "capacity_note": None, "slots": occupied}


def spawn_item(data, target_key, item_id, quantity):
    if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
        raise ValueError("Item type id must be a positive whole number.")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ValueError("Quantity must be a positive whole number.")
    slots = _resolve_container(data, target_key)
    free = [i for i, entry in enumerate(slots) if entry["id"] == 0]
    if not free:
        raise ValueError("This container is completely full - no empty slots left.")
    idx = free[0]
    slots[idx] = {"id": item_id, "amount": quantity}
    return f"Placed {quantity}x item type {item_id} into slot {idx} of {target_key}."


def remove_inventory_item(data, target_key, instance_id):
    slots = _resolve_container(data, target_key)
    if not isinstance(instance_id, int) or not (0 <= instance_id < len(slots)):
        raise ValueError("That slot doesn't exist in this container.")
    if slots[instance_id]["id"] == 0:
        raise ValueError("That slot is already empty.")
    slots[instance_id] = {"id": 0, "amount": 0}
    return f"Cleared slot {instance_id} of {target_key}."


def launch(parent):
    # Lazy import, same reasoning as games/dredge.py's own launch(): keep
    # this module (and therefore `import games`, the CLI, and every test
    # that just wants loads/dumps/the inventory hooks) usable with zero
    # PySide6 installed. Only opening the dedicated window itself needs it.
    from games.mhw_window import launch as _launch
    _launch(parent)


PROFILE = GameProfile(
    key="mhw",
    display_name="Monster Hunter World: Iceborne",
    default_save_dirs=[],
    file_patterns=[("MHW save files", "SAVEDATA1000"), ("All files", "*.*")],
    quick_fields={
        "Hunter 1 - Name": ["slots", 0, "hunter", "name"],
        "Hunter 1 - Zenny": ["slots", 0, "hunter", "zeni"],
        "Hunter 1 - HR": ["slots", 0, "hunter", "hunter_rank"],
        "Hunter 1 - MR": ["slots", 0, "hunter", "master_rank"],
        "Hunter 1 - Research Points": ["slots", 0, "hunter", "research_points"],
    },
    loads=loads,
    dumps=dumps,
    binary=True,
    custom_launcher=launch,
    notes=(
        "Opens a dedicated MHW editor window (per-hunter tabs, item pouch/"
        "storage/equipment tables, name-based pickers for both) instead of "
        "the generic tree editor - load the SAVEDATA1000 file directly "
        "from there (usually under Steam/userdata/<id>/582010/remote/). "
        "Every hunter slot (up to 3) loads together; only edit/save the "
        "ones you actually use - all three get re-encrypted together "
        "either way. Equipment entries only expose id/level/points/decos/"
        "pendant for now; armor, charms, and all 13 weapon trees resolve "
        "to real names, but kinsects don't yet (rod_insect.rod_inse is in "
        "a format this profile can't parse - see data/mhw/README.md). "
        "Decoration slots, augments, and custom upgrades round-trip "
        "untouched but aren't editable here yet."
    ),
)
PROFILE.spawn_item_targets = spawn_item_targets
PROFILE.spawn_item = spawn_item
PROFILE.inventory_state = inventory_state
PROFILE.remove_inventory_item = remove_inventory_item
PROFILE.describe_entry = _describe_entry
PROFILE.item_catalog = item_catalog
