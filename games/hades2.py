"""
Hades II game profile for cedit.

Save format:
- Binary container: SGB1 with Adler32 checksum, header metadata, and LZ4 compressed Luabins stream.
- Exposes full GameState, Resources, MetaUpgradeState, and CurrentRun in the Tree/Table view.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from lib import hades_lib
from lib.base import GameProfile

_ITEM_NAMES: dict[str, str] | None = None


def _load_item_names() -> dict[str, str]:
    global _ITEM_NAMES
    if _ITEM_NAMES is not None:
        return _ITEM_NAMES
    catalog_path = Path(__file__).parent.parent / "data" / "hades2" / "item_names.json"
    if catalog_path.is_file():
        try:
            with open(catalog_path, encoding="utf-8") as f:
                _ITEM_NAMES = json.load(f)
        except Exception:
            _ITEM_NAMES = {}
    else:
        _ITEM_NAMES = {}
    return _ITEM_NAMES


def item_name(item_id: str) -> str | None:
    names = _load_item_names()
    return names.get(item_id)


def describe_entry(parent_key: str | None, key: Any, val: Any) -> str | None:
    if parent_key == "Resources":
        name = item_name(str(key))
        if name:
            return f"{name} ({key})"
    return None


def item_catalog(data: dict[str, Any] | None) -> list[tuple[str, str]]:
    names = _load_item_names()
    rows = [(name, item_id) for item_id, name in names.items()]
    rows.sort(key=lambda r: r[0].lower())
    return rows


def spawn_item_targets(data: dict[str, Any]) -> list[tuple[str, str]]:
    return [("GameState.Resources", "Resources (Materials & Currencies)")]


def item_quantity(data: dict[str, Any], item_id: str, target: str | None = None) -> int:
    game_state = data.get("GameState", {})
    res = game_state.get("Resources", {})
    return int(res.get(item_id, 0))


def set_item_quantity(data: dict[str, Any], item_id: str, qty: int, target: str | None = None) -> None:
    if qty < 0:
        raise ValueError(f"Item quantity cannot be negative: {qty}")
    game_state = data.setdefault("GameState", {})
    res = game_state.setdefault("Resources", {})
    if qty == 0:
        res.pop(item_id, None)
    else:
        res[item_id] = float(qty)


def spawn_item(data: dict[str, Any], item_id: str, qty: int, target: str | None = None) -> None:
    current = item_quantity(data, item_id, target)
    set_item_quantity(data, item_id, current + qty, target)


def remove_item(data: dict[str, Any], item_id: str, qty: int, target: str | None = None) -> None:
    current = item_quantity(data, item_id, target)
    if current < qty:
        raise ValueError(f"Cannot remove {qty} of {item_id}; current count is {current}")
    set_item_quantity(data, item_id, current - qty, target)


def inventory_state(data: dict[str, Any]) -> dict[str, list[tuple[str, int, str]]]:
    game_state = data.get("GameState", {})
    res = game_state.get("Resources", {})
    slots = []
    for item_id, val in res.items():
        name = item_name(item_id) or item_id
        slots.append((item_id, int(val), name))
    return {"GameState.Resources": slots}


def discover_saves() -> list[str]:
    cfg_path = Path(__file__).parent.parent / "data" / "hades2.json"
    if not cfg_path.is_file():
        return []
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return []

    save_dirs = cfg.get("save_dirs", [])
    results: list[str] = []

    for dir_pattern in save_dirs:
        expanded = os.path.expandvars(os.path.expanduser(dir_pattern))
        p = Path(expanded)
        if p.is_dir():
            for f in p.iterdir():
                if f.is_file():
                    name = f.name
                    # Filter out .v.sav, .bak, .sjson, .ctrls, etc.
                    if re.match(r"^Profile[1-4](_Temp)?\.sav$", name):
                        results.append(str(f))

    results.sort(key=lambda s: os.path.getmtime(s) if os.path.exists(s) else 0, reverse=True)
    return results


def find_default_save_dir() -> str | None:
    cfg_path = Path(__file__).parent.parent / "data" / "hades2.json"
    if not cfg_path.is_file():
        return None
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return None
    for dir_pattern in cfg.get("save_dirs", []):
        expanded = os.path.expandvars(os.path.expanduser(dir_pattern))
        if os.path.isdir(expanded):
            return expanded
    return None


PROFILE = GameProfile(
    key="hades2",
    display_name="Hades II",
    default_save_dirs=["~/Library/Application Support/Supergiant Games/Hades II", "%USERPROFILE%/Saved Games/Hades II"],
    file_patterns=[("Hades II Saves", "Profile1.sav Profile2.sav Profile3.sav Profile4.sav Profile1_Temp.sav"), ("All Files", "*.* ")],
    quick_fields={'Bones': ['GameState', 'Resources', 'MetaCurrency'], 'Ash': ['GameState', 'Resources', 'MetaCardPointsCommon'], 'Psyche': ['GameState', 'Resources', 'MemPointsCommon'], 'Fate Fabric': ['GameState', 'Resources', 'MetaFabric'], 'Silver': ['GameState', 'Resources', 'OreFSilver'], 'Runs': ['Header', 'Runs']},
    loads=hades_lib.parse_sgb1_save,
    dumps=hades_lib.serialize_sgb1_save,
    binary=True,
    describe_entry=describe_entry,
    item_catalog=item_catalog,
    spawn_item_targets=spawn_item_targets,
    spawn_item=spawn_item,
    custom_launcher=None,
)
