# Monster Hunter World: Iceborne name catalogs

Two separate catalogs, because MHW itself uses two separate id spaces for
"what's in this slot":

- `item_names.json` - item pouch/storage slots (consumables, materials,
  ammo, decorations). Keyed by a bare item id.
- `equipment_names.json` - equipment slots (armor, charms, weapons). Keyed
  by `"category:type:id"` together - a bare id alone is ambiguous here
  (e.g. weapon id 10 means something different per weapon type).

Neither is from a wiki or datamine - both are parsed straight from the
game's own shipped data files, which happen to be checked into
`EnderHDMC/MHWISaveEditor`'s repo (the project `games/mhw.py`'s crypto and
struct layout were themselves reverse-engineered from - see that module's
own docstring).

## Items (`item_names.json`)

2774 entries: consumables, materials, ammo, decorations - **not**
weapons/armor, which use the separate id space below.

### How it was built

1. `itemData.itm` (`res/chunk/common/item/itemData.itm` in
   MHWISaveEditor-master) is a flat array of item records, one per id -
   parsed per that project's own `itm.bt` 010 Editor binary template
   (header + fixed 32-byte entries; only each entry's own `id` field is
   actually needed here).
2. `item_eng.gmd` (`res/chunk/common/text/steam/item_eng.gmd`) is the
   English localized text file for items - parsed per that project's own
   `gmd.bt` template (header, a hash-keyed lookup table that's skipped
   entirely, then a flat null-terminated strings block).
3. `ItemDB::ItemName()` (in that project's `data/ItemDB.cpp`) indexes the
   strings block *positionally* by `id * 2` (each item has a name string
   and a description string back to back) rather than through the GMD's
   own hash table - `id * 2 == 2774 * 2 == string_count` confirms this is
   exactly how the file is laid out. Two id pairs get swapped before
   lookup (`ItemDB::AdjustItemID`) because the game's own data has their
   names backwards: Smoke Jewel (819) <-> Survival Jewel (2270), and Igni
   Sign (956) <-> Hunter Runestone (957).
4. Each resulting name has any `<STYL ...>...</STYL>` markup (the game's
   own rich-text color/style tags) stripped down to its inner text, and is
   written out as `{id: name}`.

See `extract_item_names.py` in this folder for the actual script (reads
straight from a local `MHWISaveEditor-master` checkout's `res/chunk/`
folder).

### Coverage and quirks

- 2774 unique positive item ids (id 0 is the game's own "empty slot"
  marker and is dropped, matching `spawn_item`'s own `id <= 0` rejection).
- English names only (`item_eng.gmd`) - MHWISaveEditor-master ships the same
  file for every other supported language too (`item_jpn.gmd`,
  `item_ger.gmd`, ...), so a translated catalog is a straightforward rerun
  away if it's ever wanted.

## Equipment (`equipment_names.json`)

11421 entries covering armor, charms, all 13 weapon trees (Great Sword
through Light Bowgun), and kinsects. Keyed by `"category:type:id"`
(`mhw_equip_category`, `mhw_equip_type`, and the item's own id - the same
three fields `games/mhw.py`'s equipment struct already exposes), since a
bare id isn't unique across categories/types the way an item pouch id is.

### How it was built

1. `armor.am_dat` (armor + charms), one `<weapon>.wp_dat` or
   `<weapon>.wp_dat_g` per weapon type, and `rod_insect.rod_inse`
   (kinsects) - all under `res/chunk/common/equip/` - are each a flat
   array of equipment records, parsed per MHWISaveEditor-master's own
   `am_dat.bt`/`wp_dat.bt`/`wp_dat_g.bt`/`rod_inse.bt` 010 Editor
   templates.
2. Unlike items, every armor/weapon entry carries its own explicit
   `gmd_name_index` field (no `id * 2` positional guessing needed) -
   `data/EquipmentDB.cpp`'s `GetNameArmor`/`GetNameWeaponMelee`/
   `GetNameWeaponRanged` just read that field straight out of the matching
   `armor_eng.gmd` / `<weapon>_eng.gmd` text file. `rod_inse_entry` has no
   such field - `GetNameKinsect` instead reuses each entry's own `index`
   field directly as the string position in `rod_insect_eng.gmd`
   (confirmed by `string_count == entry_count == 105` in that file).
3. Armor entries are looked up by `(equip_slot, set_group)`, which becomes
   this catalog's `(type, id)` - `EquipmentDB::GetEntryArmor`. Weapon
   entries are looked up by `id` alone within their own weapon-type file -
   `GetEntryWeaponMelee`/`GetEntryWeaponRanged`. Kinsects are looked up by
   `equip_id` alone (`GetEntryKinsect` ignores its own `type` parameter
   entirely), stored here under a placeholder `type` of `0` since it's
   never actually consulted. Charms reuse the exact same armor table/
   lookup as armor (that's the real game's own behavior, not a
   simplification here - see `EquipmentDB::GetEquipment`'s combined
   `Armor`/`Charm` case), so this catalog's armor entries serve double duty
   for both categories.
4. Armor names also get `<ICON ALPHA/BETA/GAMMA>` markup replaced with
   actual α/β/γ characters (`EquipmentDB::GetNameArmor`'s own
   replacements), on top of the same `<STYL>` stripping items get.
5. **`rod_insect.rod_inse` is additionally Blowfish-encrypted** - the only
   one of these equipment files that is (`utility/read_bin_file.h`'s
   `ReadMetaFile(rod_inse_meta*, ...)` calls `blowfish_decrypt` on it
   before parsing, unlike every sibling overload). Same byteswap +
   Blowfish-ECB + byteswap transform `lib/mhw_crypto.py`'s
   `_blowfish_decrypt` already implements for the save file itself, just
   with its own key (`types/constants.h`'s `KEY_ROD_INSE`) and no outer
   SHA1/inner-region layer on top - decrypting it turns those
   previously-inscrutable bytes straight into the same plain
   `01 10 09 18`-magic packed struct every other equipment file here is.

See `extract_equipment_names.py` in this folder for the actual script.

### Coverage and quirks

- Category `Tool` isn't looked up by the real game's own `EquipmentDB`
  either (`GetEquipment`'s switch has no case for it) - not something this
  extraction skipped, that's upstream behavior.
- English names only, same caveat as the item catalog above.

## Regenerating either catalog

Point `BASE` in `extract_item_names.py` / `extract_equipment_names.py` at
a local `MHWISaveEditor-master` checkout's `res/chunk/common` folder and
rerun; each writes a fresh JSON file next to itself.
