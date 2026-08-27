# data/dave/

`item_names.json` - raw game item ID -> display name lookup for Dave the
Diver's `Ingredients` (materials) and `InventoryItemSlot` (general items)
storage. Vendored verbatim from
[AppleBoiy/dave-editor](https://github.com/AppleBoiy/dave-editor)'s own
`data/item_names.json`, which itself was generated from the MIT-licensed
[FNGarvin/DaveSaveEd](https://github.com/FNGarvin/DaveSaveEd) project - see
that repo's `data/README.md` for exact generation details.

Coverage: complete for cooking materials (fish/ingredients), but only a
subset of general items - it doesn't include the weapon/gear (`3xxxxxx`)
ID range, so those entries just don't have a name to show.

games/dave.py's `describe_entry` hook looks up each `Ingredients`/
`InventoryItemSlot` entry's id (`ingredientsID`/`itemID`) against this
file and shows the name next to that entry's row in cedit's tree - purely
a display hint, it never changes what gets read or written. An id with
no match in this file just shows with no name, same as before.
