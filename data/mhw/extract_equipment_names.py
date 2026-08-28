"""
One-off extraction script: am_dat (armor/charms) + 13x wp_dat/wp_dat_g
(melee/ranged weapons) + rod_inse (kinsects) -> a single equipment name
catalog JSON, keyed "category:type:id" (the exact (category, type, id)
triple a mhw_equipment save entry carries - see games/mhw.py's own
equipment struct).

Ported from MHWISaveEditor-master's own res/mapping/010 Editor/{am_dat,
wp_dat,wp_dat_g,rod_inse}.bt templates and data/EquipmentDB.cpp's
GetEntryArmor/GetEntryWeaponMelee/GetEntryWeaponRanged/GetEntryKinsect +
GetNameArmor/GetNameWeaponMelee/GetNameWeaponRanged/GetNameKinsect (see
cedit's data/mhw/README.md for the writeup). Unlike items (data/mhw/
item_names.json), armor/weapon entries carry their own explicit
gmd_name_index field - no id*2 positional-index guessing needed; kinsects
have no such field and reuse their own `index` field directly instead
(this is not a bug - EquipmentDB::GetNameKinsect does exactly this).

rod_insect.rod_inse (kinsect data) is additionally Blowfish-encrypted
(utility/read_bin_file.h's ReadMetaFile(rod_inse_meta*, ...) - the only
one of these equipment files that is) - same byteswap+Blowfish-ECB+
byteswap transform lib/mhw_crypto.py's _blowfish_decrypt already
implements for the save file itself, just with its own key
(types/constants.h's KEY_ROD_INSE). Reimplemented standalone below rather
than importing lib.mhw_crypto, so this stays a self-contained script like
extract_item_names.py.
"""
import json
import re
import struct
from pathlib import Path

from Crypto.Cipher import Blowfish

KEY_ROD_INSE = b"SFghFQVFJycHnypExurPwut98ZZq1cwvm7lpDpASeP4biRhstQgULzlb"


def _byteswap(data):
    for i in range(0, len(data), 4):
        data[i], data[i + 3] = data[i + 3], data[i]
        data[i + 1], data[i + 2] = data[i + 2], data[i + 1]


def decrypt_rod_inse(raw):
    data = bytearray(raw)
    _byteswap(data)
    cipher = Blowfish.new(KEY_ROD_INSE, Blowfish.MODE_ECB)
    data[:] = cipher.decrypt(bytes(data))
    _byteswap(data)
    return bytes(data)

# Point this at a local MHWISaveEditor-master checkout's res/chunk/common
# folder (https://github.com/EnderHDMC/MHWISaveEditor) to regenerate.
BASE = Path("MHWISaveEditor-master/res/chunk/common")
EQUIP = BASE / "equip"
STEAM_TEXT = BASE / "text" / "steam"
VFONT_TEXT = BASE / "text" / "vfont"

STYL_RE = re.compile(r"<STYL.*?>(.*?)</STYL>", re.DOTALL)
ICON_REPLACEMENTS = {
    "<ICON BETA>": " β",
    "<ICON ALPHA>": " α",
    "<ICON GAMMA>": " γ",
}


def clean_name(text):
    text = STYL_RE.sub(r"\1", text)
    for token, repl in ICON_REPLACEMENTS.items():
        text = text.replace(token, repl)
    return text.strip()


# --------------------------------------------------------------- gmd.bt
def parse_gmd_strings(path):
    raw = path.read_bytes()
    magic = raw[0:4]
    assert magic == b"GMD\x00", (path, magic)
    off = 12
    off += 8  # unknown[8]
    key_count, string_count, key_block_size, string_block_size, name_length = struct.unpack_from("<IIIII", raw, off)
    off += 20
    off += name_length + 1  # filename
    off += key_count * 32   # gmd_info_entry[key_count]
    off += 256 * 8          # buckets[256] u64
    off += key_block_size   # keys string block, skipped
    strings_block = raw[off:off + string_block_size]
    strings = strings_block.split(b"\x00")[:string_count]
    return strings


def gmd_value(strings, index):
    if index is None or index >= len(strings):
        return None
    name = strings[index].decode("utf-8", errors="replace")
    name = clean_name(name)
    return name or None


# ------------------------------------------------------------ *_dat.bt
# Each *_dat_header is identical: u32 magic, u16 version, u32 entry_count.
def _struct_from_fields(fields):
    """fields: [(name, fmt_char), ...] in .bt declaration order -> a
    struct.Struct (unaligned, matching the .bt's own byte-for-byte packed
    layout - confirmed against SAVEDATA1000.bt/gmd.bt earlier) plus the
    field name -> index map for unpack_from() results."""
    fmt = "<" + "".join(f for _n, f in fields)
    names = [n for n, _f in fields]
    return struct.Struct(fmt), names


def _read_entries_from_bytes(raw, fields):
    struct_obj, names = _struct_from_fields(fields)
    magic, version, entry_count = struct.unpack_from("<IHI", raw, 0)
    off = struct.calcsize("<IHI")
    out = []
    for _ in range(entry_count):
        values = struct_obj.unpack_from(raw, off)
        out.append(dict(zip(names, values)))
        off += struct_obj.size
    return out


def _read_entries(path, fields):
    return _read_entries_from_bytes(path.read_bytes(), fields)


AM_DAT_FIELDS = [
    ("index", "I"), ("sort_order", "H"), ("variant", "B"), ("layered_id", "H"),
    ("type", "B"), ("equip_slot", "B"), ("defense", "H"), ("model_id1", "H"),
    ("model_id2", "H"), ("icon_color", "H"), ("icon_effect", "B"), ("rarity", "B"),
    ("cost", "I"), ("res_fire", "b"), ("res_water", "b"), ("res_ice", "b"),
    ("res_thunder", "b"), ("res_dragon", "b"), ("slot_count", "B"),
    ("slot1_size", "B"), ("slot2_size", "B"), ("slot3_size", "B"),
    ("set_skill", "H"), ("set_skill_level", "B"), ("hidden_skill", "H"),
    ("hidden_skill_level", "B"), ("skill1", "H"), ("skill1_level", "B"),
    ("skill2", "H"), ("skill2_level", "B"), ("skill3", "H"), ("skill3_level", "B"),
    ("gender", "I"), ("set_group", "H"), ("gmd_name_index", "H"),
    ("gmd_description_index", "H"), ("is_permanent", "B"),
]

WP_DAT_FIELDS = [
    ("index", "I"), ("unknown0", "h"), ("base_model_id", "h"), ("part1_id", "h"),
    ("part2_id", "h"), ("unknown1", "B"), ("color", "B"), ("tree_id", "B"),
    ("is_fixed_upgrade", "B"), ("cost", "I"), ("rarity", "B"),
    ("sharpness_kire_id", "B"), ("sharpness_amount", "B"), ("damage", "H"),
    ("defense", "H"), ("affinity", "b"), ("element", "B"), ("element_damage", "H"),
    ("element_hidden", "B"), ("element_hidden_damage", "H"), ("elderseal", "B"),
    ("slot_count", "B"), ("slot1_size", "B"), ("slot2_size", "B"), ("slot3_size", "B"),
    ("special_ability1_id", "H"), ("special_ability2_id", "H"), ("unknown2", "I"),
    ("unknown3", "I"), ("unknown4", "I"), ("tree_position", "B"), ("id", "H"),
    ("gmd_name_index", "H"), ("gmd_description_index", "H"), ("skill", "H"),
    ("unknown5", "H"),
]

WP_DAT_G_FIELDS = [
    ("index", "I"), ("unknown0", "h"), ("base_model_id", "h"), ("part1_id", "h"),
    ("part2_id", "h"), ("unknown1", "B"), ("color", "B"), ("tree_id", "B"),
    ("is_fixed_upgrade", "B"), ("muzzle_type", "B"), ("barrel_type", "B"),
    ("magazine_type", "B"), ("scope_type", "B"), ("cost", "I"), ("rarity", "B"),
    ("damage", "H"), ("defense", "H"), ("affinity", "b"), ("element", "B"),
    ("element_damage", "H"), ("element_hidden", "B"), ("element_hidden_damage", "H"),
    ("elderseal", "B"), ("shell_type_id", "B"), ("unknown2", "B"), ("deviation", "B"),
    ("slot_count", "B"), ("slot1_size", "B"), ("slot2_size", "B"), ("slot3_size", "B"),
    ("unknown3", "I"), ("unknown4", "I"), ("unknown5", "I"), ("unknown6", "B"),
    ("special_ammo_type", "B"), ("tree_position", "B"), ("id", "H"),
    ("gmd_name_index", "H"), ("gmd_description_index", "H"), ("skill", "H"),
    ("unknown7", "H"),
]

ROD_INSE_FIELDS = [
    ("index", "I"), ("attack_type", "B"), ("id", "B"), ("tree_position_id", "B"),
    ("base_model_id", "H"), ("tree_id", "B"), ("craft_cost", "I"), ("rarity", "B"),
    ("power", "H"), ("speed", "H"), ("heal", "H"), ("element", "H"),
    ("dust_effect", "H"), ("tree_position", "B"), ("equip_id", "H"),
]

# type value -> (basename, is_ranged) - EquipmentDB::EquipmentDB()'s own
# BindMapping calls, in order.
WEAPON_TYPES = [
    (0, "l_sword", False, "Great Sword"),
    (1, "sword", False, "Sword And Shield"),
    (2, "w_sword", False, "Dual Blades"),
    (3, "tachi", False, "Longsword"),
    (4, "hammer", False, "Hammer"),
    (5, "whistle", False, "Hunting Horn"),
    (6, "lance", False, "Lance"),
    (7, "g_lance", False, "Gunlance"),
    (8, "s_axe", False, "Switch Axe"),
    (9, "c_axe", False, "Charge Blade"),
    (10, "rod", False, "Insect Glaive"),
    (11, "bow", True, "Bow"),
    (12, "hbg", True, "Heavy Bowgun"),
    (13, "lbg", True, "Light Bowgun"),
]

# mhw_equip_category (types/mhw_enums.h)
CATEGORY_ARMOR = 0
CATEGORY_WEAPON = 1
CATEGORY_CHARM = 2
CATEGORY_KINSECT = 4


def main():
    catalog = {}

    # --- Armor + Charms (both stored in am_dat, looked up by
    # (equip_slot, set_group) - EquipmentDB::GetEntryArmor). Every entry's
    # own category is ambiguous from am_dat alone (armor vs charm isn't a
    # field here - it's determined by which category the save's own
    # equipment.category says), so this catalog covers both categories
    # with the same (type, id) -> name mapping.
    armor_entries = _read_entries(EQUIP / "armor.am_dat", AM_DAT_FIELDS)
    armor_gmd = parse_gmd_strings(STEAM_TEXT / "armor_eng.gmd")
    for e in armor_entries:
        name = gmd_value(armor_gmd, e["gmd_name_index"])
        if not name:
            continue
        for category in (CATEGORY_ARMOR, CATEGORY_CHARM):
            key = f"{category}:{e['equip_slot']}:{e['set_group']}"
            catalog.setdefault(key, name)

    # --- Weapons (13 types, each its own wp_dat or wp_dat_g file + gmd).
    for type_id, basename, is_ranged, _label in WEAPON_TYPES:
        ext = "wp_dat_g" if is_ranged else "wp_dat"
        fields = WP_DAT_G_FIELDS if is_ranged else WP_DAT_FIELDS
        entries = _read_entries(EQUIP / f"{basename}.{ext}", fields)
        gmd_strings = parse_gmd_strings(STEAM_TEXT / f"{basename}_eng.gmd")
        for e in entries:
            name = gmd_value(gmd_strings, e["gmd_name_index"])
            if not name:
                continue
            key = f"{CATEGORY_WEAPON}:{type_id}:{e['id']}"
            catalog.setdefault(key, name)

    # --- Kinsects: rod_insect.rod_inse is Blowfish-encrypted (see this
    # module's own docstring) - decrypt first, then it's the same plain
    # packed struct every other equipment file here is. Looked up by
    # equip_id alone (EquipmentDB::GetEntryKinsect ignores its own `type`
    # parameter), and named via each entry's own `index` field directly
    # into rod_insect_eng.gmd - not a gmd_name_index field (rod_inse_entry
    # doesn't have one) and not id*2 either; this is GetNameKinsect's own
    # behavior, confirmed by string_count == entry_count (105 == 105).
    kinsect_raw = decrypt_rod_inse((EQUIP / "rod_insect.rod_inse").read_bytes())
    kinsect_entries = _read_entries_from_bytes(kinsect_raw, ROD_INSE_FIELDS)
    kinsect_gmd = parse_gmd_strings(VFONT_TEXT / "rod_insect_eng.gmd")
    for e in kinsect_entries:
        name = gmd_value(kinsect_gmd, e["index"])
        if not name:
            continue
        key = f"{CATEGORY_KINSECT}:0:{e['equip_id']}"
        catalog.setdefault(key, name)

    out_path = Path(__file__).resolve().parent / "equipment_names.json"
    out_path.write_text(
        json.dumps(dict(sorted(catalog.items())), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote {len(catalog)} equipment names -> {out_path}")
    for sample in ("0:0:0", "1:0:0", "1:11:0"):
        print(sample, catalog.get(sample))


if __name__ == "__main__":
    main()
