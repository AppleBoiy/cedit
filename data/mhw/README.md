# Monster Hunter World: Iceborne item name catalog

`item_names.json`: numeric item id -> a display name, for every item MHW's
own shipped item table knows about (2774 entries: consumables, materials,
ammo, decorations - **not** weapons/armor, which use a separate id space
this catalog doesn't cover). **Not from a wiki or datamine** - parsed
straight from the game's own `itemData.itm` + `item_eng.gmd` files, which
happen to be checked into `EnderHDMC/MHWISaveEditor`'s repo (the project
`games/mhw.py`'s crypto and struct layout were themselves reverse-engineered
from - see that module's own docstring).

## How it was built

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

## Coverage and quirks

- 2774 unique positive item ids (id 0 is the game's own "empty slot"
  marker and is dropped, matching `spawn_item`'s own `id <= 0` rejection).
- These are consumables/materials/ammo/decorations only. Equipment
  (weapons/armor) ids in `games/mhw.py`'s equipment array are a *different*
  id space, resolved through separate `wp_dat`/`am_dat`/`eq_crt`/`eq_cus`
  files this catalog doesn't parse - equipment still only shows/accepts raw
  numeric ids for now.
- English names only (`item_eng.gmd`) - MHWISaveEditor-master ships the same
  file for every other supported language too (`item_jpn.gmd`,
  `item_ger.gmd`, ...), so a translated catalog is a straightforward rerun
  away if it's ever wanted.

## Regenerating it

Point `BASE` in `extract_item_names.py` at a local `MHWISaveEditor-master`
checkout's `res/chunk/common` folder and rerun it; it writes a fresh
`item_names.json` next to itself.
