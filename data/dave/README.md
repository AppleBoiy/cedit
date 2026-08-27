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
ID range, so those entries just don't have a name to show. cedit doesn't
currently do anything with this file beyond making it available for a
future per-game name-lookup feature (see games/dave.py's profile notes) -
today, editing `Ingredients`/`InventoryItemSlot` entries is done through
the generic tree editor by raw ID, same as any other dict-of-dicts node.
