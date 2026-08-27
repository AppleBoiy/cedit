"""
cedit game profile: Escape from Duckov

Everything about the save FORMAT itself (save locations, the ES3 "missing
value key" quirk, the base64-packed item-variable fields, quick-edit
fields) is declared in data/duckov.json - none of that needed real Python.

Spawning a new item is a different story: it needs to know Duckov's own
item-tree linking scheme (see _spawn_item's docstring below), which is
too structural to express as JSON config - the "genuinely unusual"
escape hatch lib/base.py's own docstring describes. This was reverse-
engineered directly from a real save file (Item/MainCharacterItemData,
Inventory/PlayerStorage, Inventory/Inventory_Safe), not from any
published schema - Escape from Duckov doesn't have one.

There is deliberately no item name catalog here (unlike Dave/Octopath/
DREDGE): no such catalog exists publicly for Duckov, so spawn_item takes
a raw numeric item type id (find one via a wiki/datamine) rather than a
name. See _spawn_item's docstring for what "quantity" actually does and
why.
"""
from pathlib import Path

from lib.base import GameProfile

# Path(__file__).resolve() (not os.path.dirname(__file__) + "..") because
# under a PyInstaller bundle, games/*.py is embedded straight into the
# frozen archive - __file__ points at a synthetic "games/duckov.py" path
# whose "games" directory never actually exists on disk. A literal
# ".."-containing path like ".../games/../data/x.json" then fails to open
# (the OS has to actually enter "games" before it can apply ".."), even
# though "data" itself is a real, present directory. Path.resolve() (non-
# strict by default) collapses ".." lexically instead, so it works whether
# or not the intermediate directory is real.
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "duckov.json"


# --------------------------------------------------------------- item tree
#
# Two related container shapes recur throughout a Duckov save:
#
#   ItemTreeData:  {"rootInstanceID": <id>, "entries": [ItemEntry, ...]}
#     One entry per item anywhere in that tree (the root entry itself,
#     everything it has equipped, everything inside anything it's
#     carrying...). Appears at Item/MainCharacterItemData (the player's
#     worn/carried items), Item/LastDeadCharacter, Item/Showcase_BaseSkin.
#
#   ItemEntry: {"instanceID": <id>, "typeID": <item type>, "variables":
#     [...packed stat blobs, already decoded generically via
#     packed_value_node...], "slotContents": [{"slot": <name>,
#     "instanceID": <id>}, ...] (named equipment slots - weapon, armor,
#     etc), "inventory": [{"position": <n>, "instanceID": <id>}, ...]
#     (grid-positioned contents, e.g. what's inside a backpack),
#     "inventorySortLocks": [...]}.
#
#   InventoryData: {"capacity": <n>, "entries": [{"inventoryPosition":
#     <n>, "itemTreeData": ItemTreeData}, ...], "lockedIndexes": [...]}
#     A flat, capacity-bounded grid of item stacks, one ItemTreeData per
#     occupied slot (so even a single stackable item, like ammo, is its
#     own tiny one-entry tree). Appears at Inventory/PlayerStorage and
#     Inventory/Inventory_Safe.
#
# instanceIDs are negative and, in every save inspected, only ever get
# more negative as more items are created - but there's no persisted
# "next id" counter anywhere in the save to read (the game apparently
# tracks that only at runtime), so a freshly spawned item's id is chosen
# as one less than the most negative instanceID found ANYWHERE in the
# save (every container, recursively) - guaranteed to not collide with
# anything already in the file, which is the only thing within cedit's
# control.

_SPAWN_TARGETS = [
    ("Backpack (worn inventory)", "backpack"),
    ("Player Storage (Base)", "playerstorage"),
    ("Storage Safe", "safe"),
]
_INVENTORY_DATA_KEYS = {
    "playerstorage": "Inventory/PlayerStorage",
    "safe": "Inventory/Inventory_Safe",
}


def _collect_instance_ids(node, out):
    if isinstance(node, dict):
        value = node.get("instanceID")
        if isinstance(value, int) and not isinstance(value, bool):
            out.add(value)
        for v in node.values():
            _collect_instance_ids(v, out)
    elif isinstance(node, list):
        for v in node:
            _collect_instance_ids(v, out)


def _next_instance_ids(data, count):
    """count freshly allocated, mutually-unique instanceIDs, each more
    negative than every instanceID currently anywhere in the save."""
    seen = set()
    _collect_instance_ids(data, seen)
    start = (min(seen) - 1) if seen else -1
    return list(range(start, start - count, -1))


def _blank_item_entry(instance_id, item_id):
    return {
        "instanceID": instance_id,
        "typeID": item_id,
        "variables": [],
        "slotContents": [],
        "inventory": [],
        "inventorySortLocks": [],
    }


def spawn_item_targets(data):
    return list(_SPAWN_TARGETS)


def spawn_item(data, target_key, item_id, quantity):
    """Create `quantity` new items of type `item_id` in the container
    `target_key` identifies (one of _SPAWN_TARGETS' keys).

    Each unit of quantity is its own separate item-tree entry rather than
    a single entry with a "Count" stat set to quantity: whether an item
    type is actually stackable (and under which variable) is something
    only the game's own item catalog knows, which this profile doesn't
    have - guessing wrong would create a `Count` variable the game simply
    ignores for a non-stackable item, silently spawning only 1 instead of
    the requested amount. Separate entries always work, at the cost of
    using one inventory slot per unit for anything that IS stackable in
    game (mergeable afterwards through the game's own UI).
    """
    if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
        raise ValueError("Item type id must be a positive whole number.")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ValueError("Quantity must be a positive whole number.")

    if target_key == "backpack":
        return _spawn_into_backpack(data, item_id, quantity)
    if target_key in _INVENTORY_DATA_KEYS:
        return _spawn_into_inventory_data(data, _INVENTORY_DATA_KEYS[target_key], item_id, quantity)
    raise ValueError(f"Unknown spawn target {target_key!r}.")


def _spawn_into_backpack(data, item_id, quantity):
    container = data.get("Item/MainCharacterItemData")
    if not isinstance(container, dict) or "value" not in container:
        raise ValueError("This save has no Item/MainCharacterItemData to spawn into.")
    tree = container["value"]
    entries = tree.get("entries")
    root_id = tree.get("rootInstanceID")
    if not isinstance(entries, list) or root_id is None:
        raise ValueError("Item/MainCharacterItemData doesn't look like a valid item tree.")
    root_entry = next((e for e in entries if e.get("instanceID") == root_id), None)
    if root_entry is None:
        raise ValueError("Couldn't find the root item entry (the player themselves) in this tree.")

    inventory = root_entry.setdefault("inventory", [])
    used_positions = {c.get("position") for c in inventory}
    new_ids = _next_instance_ids(data, quantity)

    position = 0
    placed = 0
    while placed < quantity:
        if position not in used_positions:
            new_id = new_ids[placed]
            entries.append(_blank_item_entry(new_id, item_id))
            inventory.append({"position": position, "instanceID": new_id})
            used_positions.add(position)
            placed += 1
        position += 1

    return (
        f"Spawned {quantity}x item type {item_id} into the backpack "
        f"(no known capacity limit for this container - check in-game "
        f"that they actually fit)."
    )


def _spawn_into_inventory_data(data, container_key, item_id, quantity):
    container = data.get(container_key)
    if not isinstance(container, dict) or "value" not in container:
        raise ValueError(f"This save has no {container_key} to spawn into.")
    inv = container["value"]
    entries = inv.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"{container_key} doesn't look like a valid inventory.")
    capacity = inv.get("capacity")
    used_positions = {e.get("inventoryPosition") for e in entries}

    if isinstance(capacity, int):
        free_slots = capacity - len(used_positions)
        if free_slots < quantity:
            raise ValueError(
                f"{container_key} only has {max(free_slots, 0)} free slot(s) "
                f"(capacity {capacity}); can't fit {quantity}."
            )

    new_ids = _next_instance_ids(data, quantity)
    position = 0
    placed = 0
    while placed < quantity:
        if position not in used_positions:
            new_id = new_ids[placed]
            entries.append({
                "inventoryPosition": position,
                "itemTreeData": {
                    "rootInstanceID": new_id,
                    "entries": [_blank_item_entry(new_id, item_id)],
                },
            })
            used_positions.add(position)
            placed += 1
        position += 1
        if isinstance(capacity, int) and position >= capacity and placed < quantity:
            raise ValueError(f"{container_key} ran out of room while spawning.")

    return f"Spawned {quantity}x item type {item_id} into {container_key}."


PROFILE = GameProfile.from_config(_CONFIG_PATH)
PROFILE.spawn_item_targets = spawn_item_targets
PROFILE.spawn_item = spawn_item
