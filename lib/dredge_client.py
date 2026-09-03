"""
Python side of the DREDGE integration.

DREDGE saves are .NET BinaryFormatter blobs. They can only be read/written
with the game's own compiled types, so this does NOT parse the save format
itself - it shells out to a small C# "bridge" program (vendored in
lib/dredge_bridge/, adapted from AppleBoiy/dredge-se) that loads the game's
own Assembly-CSharp.dll via reflection and does the real deserialize/patch/
reserialize. This module just builds/invokes that bridge and validates
patches client-side before sending them (mirroring the validation the
upstream project's web UI does, and which the bridge itself re-checks).

Bridge CLI contract (see lib/dredge_bridge/Program.cs):
    dotnet <bridge.dll> inspect <save-path> <managed-dir>
    dotnet <bridge.dll> edit    <save-path> <managed-dir> <patch.json>
  -> prints one JSON object to stdout on success ({"ok": true, ...}),
     or to stderr with a nonzero exit code on failure ({"ok": false, "error": ...}).
"""

import contextlib
import json
import os
import platform
import subprocess
from pathlib import Path

BRIDGE_DIR = Path(__file__).resolve().parent / "dredge_bridge"
BRIDGE_PROJECT = BRIDGE_DIR / "DredgeSaveBridge.csproj"
BRIDGE_DLL = BRIDGE_DIR / "bin" / "Debug" / "net10.0" / "DredgeSaveBridge.dll"

VARIABLE_GROUPS = ("decimals", "integers", "floats", "strings", "booleans")
CONTAINERS = ("inventory", "storage", "overflowStorage", "nonSpatialItems")


class DredgeBridgeError(RuntimeError):
    """Raised when the dotnet bridge itself reports a failure."""


# --------------------------------------------------------------------- paths

def candidate_locations():
    """Per-OS default (saves-dir-list, managed-dir-list), ported from dredge.mjs."""
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        return (
            [home / "Library/Application Support/Black Salt Games/DREDGE/saves"],
            [home / "Library/Application Support/Steam/steamapps/common/DREDGE"
                    "/DREDGE.app/Contents/Resources/Data/Managed"],
        )
    if system == "Windows":
        local_low = Path(os.environ.get("USERPROFILE", str(home))) / "AppData/LocalLow/Black Salt Games/DREDGE"
        steam = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))  # noqa: SIM112 - real Windows env var name, lookups are case-insensitive there
        return (
            [local_low / "saves", local_low / "eos/saves", local_low / "gog_galaxy/saves"],
            [steam / "Steam/steamapps/common/DREDGE/DREDGE_Data/Managed"],
        )
    return (
        [home / ".steam/steam/steamapps/compatdata/1562430/pfx/drive_c/users/steamuser"
               "/AppData/LocalLow/Black Salt Games/DREDGE/saves"],
        [home / ".steam/steam/steamapps/common/DREDGE/DREDGE_Data/Managed"],
    )


def first_existing(paths):
    for p in paths:
        if p.exists():
            return p
    return None


def find_managed_dir():
    _, managed = candidate_locations()
    return first_existing(managed)


def discover_saves():
    saves_dirs, _ = candidate_locations()
    found = []
    for d in saves_dirs:
        if not d.exists():
            continue
        for name in sorted(os.listdir(d)):
            if name.startswith("dredge-save") and name.endswith(".bin") and len(name) == len("dredge-saveN.bin"):
                found.append(d / name)
    return found


# ------------------------------------------------------------------- bridge

def ensure_bridge_built():
    if BRIDGE_DLL.exists():
        return
    if not shutil_which("dotnet"):
        raise DredgeBridgeError(
            "The 'dotnet' SDK was not found on PATH. Install .NET SDK 10+ to use DREDGE support."
        )
    proc = subprocess.run(
        ["dotnet", "build", str(BRIDGE_PROJECT)],
        cwd=str(BRIDGE_DIR), capture_output=True, text=True,
    )
    if proc.returncode != 0 or not BRIDGE_DLL.exists():
        raise DredgeBridgeError("Building the DREDGE bridge failed:\n" + (proc.stderr or proc.stdout))


def shutil_which(cmd):
    import shutil
    return shutil.which(cmd)


def _run_bridge(command, save_path, managed_dir, patch_path=None):
    ensure_bridge_built()
    args = ["dotnet", str(BRIDGE_DLL), command, str(save_path), str(managed_dir)]
    if patch_path is not None:
        args.append(str(patch_path))
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or f"bridge exited with code {proc.returncode}"
        with contextlib.suppress(json.JSONDecodeError, AttributeError):
            message = json.loads(message).get("error", message)
        raise DredgeBridgeError(message)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise DredgeBridgeError(f"Bridge produced non-JSON output: {exc}\n{proc.stdout[:500]}") from exc


def inspect_save(save_path, managed_dir):
    return _run_bridge("inspect", save_path, managed_dir)


def edit_save(save_path, managed_dir, patch, patch_path):
    """Writes `patch` to patch_path, invokes the bridge's `edit`, returns its JSON result."""
    with open(patch_path, "w", encoding="utf-8") as fh:
        json.dump(patch, fh)
    return _run_bridge("edit", save_path, managed_dir, patch_path)


# --------------------------------------------------------------- validation
# Client-side mirror of upstream's src/dredge.mjs validatePatch/validateInventoryOps.
# This is defense in depth - the bridge (Program.cs ApplyPatch/ApplyInventoryOperations)
# re-validates everything independently before touching the file.

def validate_patch(original_variables, patch):
    if not isinstance(patch, dict):
        raise ValueError("Patch must be an object")
    for group, values in patch.items():
        if group not in VARIABLE_GROUPS or not isinstance(values, dict):
            raise ValueError(f"Invalid variable group: {group}")
        known = original_variables.get(group, {}) or {}
        for key, value in values.items():
            if key not in known:
                raise ValueError(f"Unknown {group} key: {key}")
            if group == "booleans" and not isinstance(value, bool):
                raise ValueError(f"{key} must be true or false")
            if group == "strings" and not isinstance(value, str):
                raise ValueError(f"{key} must be text")
            if group not in ("booleans", "strings"):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{key} must be a finite number")
                if group == "integers" and not float(value).is_integer():
                    raise ValueError(f"{key} must be a whole number")
    return patch


def _container_items(save, name):
    mapping = {
        "inventory": (save.get("inventory") or {}).get("items", []),
        "storage": (save.get("storage") or {}).get("items", []),
        "overflowStorage": (save.get("overflowStorage") or {}).get("items", []),
        "nonSpatialItems": save.get("nonSpatialItems", []),
    }
    return mapping.get(name)


def validate_inventory_ops(save, operations, item_catalog=None):
    item_catalog = item_catalog or {}
    if not isinstance(operations, list):
        raise ValueError("Inventory operations must be a list")
    if len(operations) > 100:
        raise ValueError("At most 100 inventory operations are allowed")

    def check_coord(op, key):
        value = op.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or not (0 <= value <= 99):
            raise ValueError(f"{key} must be a whole number from 0 to 99")
        return value

    def check_rotation(op):
        z = op.get("z", 0)
        if z not in (0, 90, 180, 270):
            raise ValueError("Rotation must be 0, 90, 180, or 270")
        return z

    normalized = []
    for op in operations:
        if not isinstance(op, dict):
            raise ValueError("Invalid inventory operation")
        action = op.get("action")

        if action == "spawn":
            item_id, target = op.get("id"), op.get("target")
            if not isinstance(item_id, str) or item_id not in item_catalog:
                raise ValueError(f"Unknown spawn item: {item_id}")
            if target not in ("inventory", "storage", "overflowStorage"):
                raise ValueError(f"Unknown spawn target: {target}")
            result = {"action": "spawn", "id": item_id, "target": target,
                      "x": check_coord(op, "x"), "y": check_coord(op, "y"), "z": check_rotation(op)}
            asset = item_catalog[item_id]
            result["runtimeType"] = ("FishItemInstance" if asset.get("itemType") == 1
                                      and asset.get("itemSubtype") == 1 else "SpatialItemInstance")
            normalized.append(result)
            continue

        if action not in ("remove", "duplicate", "move"):
            raise ValueError(f"Unknown inventory action: {action}")
        container, index, item_id = op.get("container"), op.get("index"), op.get("id")
        items = _container_items(save, container)
        if items is None:
            raise ValueError(f"Unknown item container: {container}")
        if not isinstance(index, int) or isinstance(index, bool) or not (0 <= index < len(items)):
            raise ValueError(f"Invalid {container} item index")
        row = items[index] if index < len(items) else None
        actual_id = (row or {}).get("values", {}).get("id")
        if not isinstance(item_id, str) or actual_id != item_id:
            raise ValueError(f"{container} item changed; reload the save")

        if action == "remove":
            normalized.append({"action": "remove", "container": container, "index": index, "id": item_id})
            continue
        if action == "move":
            if container == "nonSpatialItems":
                raise ValueError("Cabin items cannot be placed on a grid")
            normalized.append({"action": "move", "container": container, "index": index, "id": item_id,
                                "x": check_coord(op, "x"), "y": check_coord(op, "y"), "z": check_rotation(op)})
            continue
        # duplicate
        target = op.get("target") or ("nonSpatialItems" if container == "nonSpatialItems" else "overflowStorage")
        if _container_items(save, target) is None:
            raise ValueError(f"Unknown target container: {target}")
        if (container == "nonSpatialItems") != (target == "nonSpatialItems"):
            raise ValueError("Spatial and non-spatial item containers cannot be mixed")
        result = {"action": "duplicate", "container": container, "index": index, "id": item_id, "target": target}
        if container != "nonSpatialItems":
            result["x"] = op.get("x", 0)
            result["y"] = op.get("y", len(_container_items(save, target)))
            result["z"] = op.get("z", 0)
            for key in ("x", "y"):
                if not isinstance(result[key], int) or isinstance(result[key], bool) or not (0 <= result[key] <= 99):
                    raise ValueError(f"{key} must be a whole number from 0 to 99")
            if result["z"] not in (0, 90, 180, 270):
                raise ValueError("Rotation must be 0, 90, 180, or 270")
        normalized.append(result)

    spawns = [o for o in normalized if o["action"] == "spawn"]
    duplicates = [o for o in normalized if o["action"] == "duplicate"]
    moves = [o for o in normalized if o["action"] == "move"]
    removals = sorted(
        (o for o in normalized if o["action"] == "remove"),
        key=lambda o: (o["container"], -o["index"]),
    )
    return spawns + duplicates + moves + removals


MANIFEST_PATH = BRIDGE_DIR.parent.parent / "data" / "dredge" / "manifest.json"


def _load_manifest():
    """Loads data/dredge/manifest.json, generated locally by upstream's
    tools/extract_game_assets.py against the user's own installed game assets.
    It isn't something we can ship, so catalog-dependent features (spawn,
    real item shapes, real grid layouts) simply aren't available until the
    user generates and drops one in."""
    if not MANIFEST_PATH.exists():
        return {}
    try:
        with open(MANIFEST_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def load_item_catalog():
    """{item_id: {"id","name","sprite","dimensions","itemType","itemSubtype",
    "forbidStorageTray"}} from the manifest's "items" map."""
    return _load_manifest().get("items", {})


def load_grid_configs():
    """{"Tier1Hull".."Tier5Hull", "Storage", "OverflowStorage"}: each
    {"columns", "rows", "cells": {(x, y): {"itemType", "itemSubtype"}}}.

    A cell's itemType of 0 means that cell isn't usable at all (outside the
    hull/storage at that upgrade tier, a bulkhead, etc) - this is how real
    "available space" is only a subset of the rows x columns rectangle, and
    why it changes as the boat's hull-tier variable changes. -1 means the
    cell accepts anything; otherwise it's a bitmask matched against an
    item's own itemType/itemSubtype (ported from upstream's acceptsItem in
    public/app.js)."""
    grids = _load_manifest().get("grids", {})
    result = {}
    for name, grid in grids.items():
        cells = {
            (cell["x"], cell["y"]): {
                "itemType": cell.get("itemType", 0),
                "itemSubtype": cell.get("itemSubtype", 0),
            }
            for cell in grid.get("cells", [])
        }
        result[name] = {"columns": grid.get("columns"), "rows": grid.get("rows"), "cells": cells}
    return result


def grid_config_name_for(container, hull_tier=1):
    """Which manifest grid config applies to a container - the boat's own
    cargo grid depends on its hull-tier variable (clamped 1-5, upstream
    defaults to 1); Storage/OverflowStorage each have one fixed layout."""
    if container == "inventory":
        tier = max(1, min(5, int(hull_tier or 1)))
        return f"Tier{tier}Hull"
    if container == "storage":
        return "Storage"
    if container == "overflowStorage":
        return "OverflowStorage"
    return None


def cell_accepts(grid_config, x, y, item_type, item_subtype):
    """Port of upstream's acceptsItem(): can an item with this
    itemType/itemSubtype legally occupy this cell? Returns True (permissive)
    when there's no grid config at all - i.e. we don't actually know, so we
    don't block anything we can't justify."""
    if grid_config is None:
        return True
    cell = grid_config["cells"].get((x, y))
    if cell is None or cell["itemType"] == 0:
        return False
    type_ok = cell["itemType"] == -1 or item_type == -1 or (cell["itemType"] & item_type) != 0
    subtype_ok = cell["itemSubtype"] == -1 or item_subtype == -1 or (cell["itemSubtype"] & item_subtype) != 0
    return type_ok and subtype_ok
