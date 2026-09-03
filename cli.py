#!/usr/bin/env python3
"""
cedit-cli - scriptable, headless access to cedit's game profiles.

Every GameProfile hook (loads/dumps, spawn_item, inventory_state,
item_catalog, get_by_path/set_by_path...) is plain Python with no PySide6
dependency - only cedit.py itself (the GUI) and games/dredge_window.py
(DREDGE's own window, imported lazily - see games/dredge.py's docstring)
touch Qt. This file reuses those same hooks directly, so it works in a
plain Python environment with no GUI toolkit installed at all, and is
safe to call from scripts, cron jobs, or CI.

DREDGE is the one profile this can't touch: it has no loads/dumps (its
save is a .NET BinaryFormatter blob only DREDGE's own compiled types can
deserialize - see games/dredge.py), so every command below rejects it
with a clear message rather than pretending to support it.

Examples:
    python3 cli.py list-games
    python3 cli.py get --game duckov --save Save_1.sav --path EconomyData.value.money
    python3 cli.py set --game duckov --save Save_1.sav --path EconomyData.value.money --value 999999
    python3 cli.py targets --game duckov --save Save_1.sav
    python3 cli.py inventory --game duckov --save Save_1.sav --target backpack
    python3 cli.py spawn --game duckov --save Save_1.sav --target backpack --item 594 --quantity 3
    python3 cli.py remove --game duckov --save Save_1.sav --target backpack --instance -116
    python3 cli.py catalog --game duckov --search rifle
"""
import argparse
import json
import os
import sys
from pathlib import Path

from games import get_game, list_games
from lib.base import (
    atomic_write_bytes,
    atomic_write_text,
    backup_file,
    coerce_value,
    get_by_path,
    set_by_path,
    smart_parse,
)


def _read_version():
    """VERSION at the repo root, or bundled alongside cedit-cli via
    packaging/cedit_cli.spec's datas - see cedit.py's identical helper
    (not shared/imported: this file deliberately has zero dependency on
    cedit.py, which would drag in PySide6-adjacent module-level code)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(base, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "dev"


__version__ = _read_version()


class CliError(Exception):
    """Raised for any user-facing failure - caught once in main() and
    printed to stderr, so every cmd_*() function can just raise this
    instead of duplicating error-formatting/exit-code logic."""


def _require_scriptable(profile):
    if profile.custom_launcher is not None:
        raise CliError(
            f"{profile.display_name} doesn't support CLI access - it has no loads/dumps "
            f"of its own (see games/{profile.key}.py's docstring for why)."
        )


def _load(profile, save_path):
    _require_scriptable(profile)
    try:
        if profile.binary:
            with open(save_path, "rb") as f:
                raw = f.read()
        else:
            with open(save_path, encoding="utf-8-sig") as f:
                raw = f.read()
    except OSError as e:
        raise CliError(f"Couldn't open {save_path}: {e}") from e
    try:
        return profile.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise CliError(f"Couldn't parse {save_path} as a {profile.display_name} save: {e}") from e


def _save(profile, data, save_path, *, backup=True):
    try:
        payload = profile.dump(data)
    except (TypeError, ValueError) as e:
        raise CliError(f"Couldn't serialize the data: {e}") from e

    if profile.pre_save_check:
        try:
            block_reason = profile.pre_save_check(save_path)
        except Exception:
            block_reason = None
        if block_reason:
            raise CliError(f"Refusing to save: {block_reason}")

    if backup and Path(save_path).exists():
        try:
            backup_file(save_path)
        except OSError as e:
            raise CliError(f"Couldn't create a backup before saving (use --no-backup to skip): {e}") from e

    try:
        if profile.binary:
            atomic_write_bytes(save_path, payload)
        else:
            atomic_write_text(save_path, payload)
    except OSError as e:
        raise CliError(f"Couldn't save {save_path}: {e}") from e


def _parse_path(path_str):
    """"EconomyData.value.money" -> ["EconomyData", "value", "money"], with
    any all-digit segment (optionally negative) treated as a list index."""
    if not path_str:
        return []
    parts = []
    for segment in path_str.split("."):
        if segment.lstrip("-").isdigit():
            parts.append(int(segment))
        else:
            parts.append(segment)
    return parts


def _print_json(value):
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


# --------------------------------------------------------------- commands

def cmd_list_games(args):
    for profile in list_games():
        scope = "custom_launcher only - no CLI support" if profile.custom_launcher else "scriptable"
        print(f"{profile.key}\t{profile.display_name}\t({scope})")


def cmd_get(args):
    profile = get_game(args.game)
    data = _load(profile, args.save)
    parts = _parse_path(args.path)
    try:
        value = get_by_path(data, parts) if parts else data
    except (KeyError, IndexError, TypeError) as e:
        raise CliError(f"Path {args.path!r} not found: {e}") from e
    _print_json(value)


def cmd_set(args):
    profile = get_game(args.game)
    data = _load(profile, args.save)
    parts = _parse_path(args.path)
    if not parts:
        raise CliError("--path is required for set (can't replace the whole save file this way)")

    if args.json:
        try:
            value = json.loads(args.value)
        except json.JSONDecodeError as e:
            raise CliError(f"--value isn't valid JSON: {e}") from e
    else:
        try:
            original = get_by_path(data, parts)
        except (KeyError, IndexError, TypeError):
            original = None
        # Match the existing value's type when there is one (same rule
        # cedit.py's tree editor uses); otherwise best-effort guess, same
        # as typing a brand-new value into the GUI's Add Key dialog.
        value = coerce_value(args.value, original) if original is not None else smart_parse(args.value)

    try:
        set_by_path(data, parts, value)
    except (KeyError, IndexError, TypeError) as e:
        raise CliError(f"Couldn't set {args.path!r}: {e}") from e

    _save(profile, data, args.save, backup=not args.no_backup)
    print(f"Set {args.path} = {value!r} in {args.save}")


def cmd_targets(args):
    profile = get_game(args.game)
    if profile.spawn_item_targets is None:
        raise CliError(f"{profile.display_name} has no spawn targets.")
    data = _load(profile, args.save)
    for label, key in profile.spawn_item_targets(data):
        print(f"{key}\t{label}")


def cmd_inventory(args):
    profile = get_game(args.game)
    if profile.inventory_state is None:
        raise CliError(f"{profile.display_name} doesn't support inventory browsing via cedit.")
    data = _load(profile, args.save)
    try:
        state = profile.inventory_state(data, args.target)
    except ValueError as e:
        raise CliError(str(e)) from e
    _print_json(state)


def cmd_spawn(args):
    profile = get_game(args.game)
    if profile.spawn_item is None:
        raise CliError(f"{profile.display_name} doesn't support spawning items via cedit.")
    data = _load(profile, args.save)
    try:
        message = profile.spawn_item(data, args.target, args.item, args.quantity)
    except ValueError as e:
        raise CliError(f"Couldn't spawn item: {e}") from e
    _save(profile, data, args.save, backup=not args.no_backup)
    print(message)


def cmd_remove(args):
    profile = get_game(args.game)
    if profile.remove_inventory_item is None:
        raise CliError(f"{profile.display_name} doesn't support removing items via cedit.")
    data = _load(profile, args.save)
    try:
        message = profile.remove_inventory_item(data, args.target, args.instance)
    except ValueError as e:
        raise CliError(f"Couldn't remove item: {e}") from e
    _save(profile, data, args.save, backup=not args.no_backup)
    print(message)


def cmd_catalog(args):
    profile = get_game(args.game)
    if profile.item_catalog is None:
        raise CliError(f"{profile.display_name} has no item catalog.")
    data = _load(profile, args.save) if args.save else None
    rows = profile.item_catalog(data)
    needle = (args.search or "").strip().lower()
    for name, item_id in rows:
        if needle and needle not in name.lower() and needle not in str(item_id).lower():
            continue
        print(f"{item_id}\t{name}")


# ----------------------------------------------------------------- parser

def build_parser():
    game_keys = [p.key for p in list_games()]

    parser = argparse.ArgumentParser(
        prog="cedit-cli",
        description="Scriptable, headless access to cedit's game profiles - see this file's module docstring for examples.",
    )
    parser.add_argument("--version", action="version", version=f"cedit-cli {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-games", help="List every registered game profile").set_defaults(func=cmd_list_games)

    def add_common(p, *, target=False, no_backup=True):
        p.add_argument("--game", required=True, choices=game_keys)
        p.add_argument("--save", required=True, help="Path to the save file")
        if no_backup:
            p.add_argument("--no-backup", action="store_true", help="Skip the automatic .bak before writing")
        if target:
            p.add_argument("--target", required=True, help="A key from `targets`'s output")

    p = sub.add_parser("get", help="Print a value (or the whole save) as JSON")
    add_common(p, no_backup=False)
    p.add_argument("--path", default="", help='Dot-separated path, e.g. "EconomyData.value.money" (omit for the whole save)')
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("set", help="Set a value and write the save back (with a .bak first, unless --no-backup)")
    add_common(p)
    p.add_argument("--path", required=True, help='Dot-separated path, e.g. "EconomyData.value.money"')
    p.add_argument("--value", required=True, help="New value, as text (or JSON with --json)")
    p.add_argument("--json", action="store_true", help="Parse --value as a JSON literal instead of matching the existing type")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("targets", help="List a profile's spawn/inventory container keys")
    add_common(p, no_backup=False)
    p.set_defaults(func=cmd_targets)

    p = sub.add_parser("inventory", help="Print one container's occupied slots + capacity as JSON")
    add_common(p, target=True, no_backup=False)
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("spawn", help="Spawn a new item into a container")
    add_common(p, target=True)
    p.add_argument("--item", required=True, type=int, help="Numeric item type id")
    p.add_argument("--quantity", type=int, default=1)
    p.set_defaults(func=cmd_spawn)

    p = sub.add_parser("remove", help="Remove an item from a container by instance id")
    add_common(p, target=True)
    p.add_argument("--instance", required=True, type=int, help="Instance id, from `inventory`'s output")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("catalog", help="List (and optionally search) a profile's item name catalog")
    p.add_argument("--game", required=True, choices=game_keys)
    p.add_argument("--save", help="Only needed if this profile's catalog depends on save data (most don't)")
    p.add_argument("--search", help="Case-insensitive substring filter over name/id")
    p.set_defaults(func=cmd_catalog)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except CliError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
