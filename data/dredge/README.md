manifest.json goes here (optional).

Without it, cedit's DREDGE editor still fully supports:
  - editing primitive save variables (decimals/integers/floats/strings/booleans)
  - moving, removing, and duplicating existing inventory items on the grid

It just can't validate/spawn *new* items by id, and draws every item as a
single grid cell (no real footprint shape), because it has no item catalog
to look those up in.

To enable that, clone https://github.com/AppleBoiy/dredge-se, run its
tools/extract_game_assets.py against your local DREDGE install to generate
public/game-assets/manifest.json, and copy that file here unchanged (it's
expected to have the shape {"items": {"<id>": {"itemType":..., "itemSubtype":...,
"dimensions":[{"x":0,"y":0}, ...]}, ...}}).
