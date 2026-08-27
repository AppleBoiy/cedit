# Duckov item name catalog

`item_names.json`: numeric item `typeID` -> a display name, for every item
prefab cedit could find. **Not from a wiki or datamine** - extracted
directly from your own local install of Escape from Duckov.

## How it was built

1. [AssetRipper](https://github.com/AssetRipper/AssetRipper) exported the
   game's Unity project from `Duckov.app/Contents/Resources/Data`
   (Export Unity Project).
2. Every item in this game turns out to be a `.prefab` under
   `Assets/GameObject/` with a component carrying a `typeID: <int>` field -
   the exact same field name the save format itself uses
   (`ItemStatsSystem.Data.ItemTreeData`'s `typeID`, see games/duckov.py's
   own docstring). The prefab's own GameObject name (e.g. `BackpackLV1`,
   `AR_AK47_Fire`, `Bandage`) becomes that id's display name.
3. Regex-scanned every `.prefab` for `typeID:` + `m_Name:` and wrote the
   pairs out as this JSON file - no game code needed, no DLL decompiling.

## Coverage and quirks

- 1568 unique positive type ids. Ids `<= 0` (`0`, `-1`, ...) were dropped -
  those turned out to be non-item prefabs (`Character`, level-scaffolding
  objects), not anything spawn_item would accept anyway (it already
  rejects `id <= 0`).
- Names are the *internal* prefab names, not always the exact in-game
  display string a player would see (no localization was pulled in) - e.g.
  `S_AK74_Lv_2` rather than a fully formatted weapon name. Close enough to
  identify what an id actually is; treat it as "clearly better than a bare
  number," not as a verbatim UI label.
- A handful of ids (3 out of 1568) had more than one prefab sharing the
  same `typeID` - a leftover/duplicate asset in the game's own project.
  Whichever prefab sorts first alphabetically by filename was kept; this
  is a genuine, minor ambiguity in the source data, not a bug in the
  extraction.
- If TeamSoda ships an update that adds/renumbers items, this file goes
  stale until someone re-runs the extraction against the new install and
  copies over a fresh `item_names.json`. There's no automated way to
  detect that from inside cedit.

## Regenerating it

1. Export the game via AssetRipper as above.
2. In the exported project's `Assets/GameObject/` folder, run:
   ```python
   import re, glob, json
   items = {}
   for path in sorted(glob.glob("*.prefab")):
       text = open(path, encoding="utf-8", errors="replace").read()
       m_type = re.search(r'^\s*typeID:\s*(-?\d+)\s*$', text, re.MULTILINE)
       if not m_type:
           continue
       type_id = int(m_type.group(1))
       if type_id <= 0:
           continue
       m_name = re.search(r'GameObject:\n(?:.*\n)*?\s*m_Name:\s*(.+)\s*$', text, re.MULTILINE)
       name = m_name.group(1).strip() if m_name else path[:-7]
       items.setdefault(type_id, name)
   json.dump({str(k): v for k, v in sorted(items.items())}, open("item_names.json", "w"), indent=2, ensure_ascii=False)
   ```
3. Copy the result over this file.
