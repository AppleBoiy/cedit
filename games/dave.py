"""
cedit game profile: Dave the Diver (Steam / macOS)

Save format: *_GD.sav files are JSON, obfuscated with a repeating XOR
cipher keyed on the ASCII string "GameData", applied per UTF-16 code unit
(not per byte - important so saves containing non-ASCII text, e.g. CJK
names, don't corrupt). This is the same scheme the game itself uses.
Only *_GD.sav files (main game data: currencies, inventory, chapter
progress, achievements) use this scheme in a directly JSON-decodable way;
the PZ/UO/PD files in the same save folder hold other subsystems and
aren't touched here.

Ported from https://github.com/AppleBoiy/dave-editor, a standalone
Tkinter tool for this same save format built earlier - see that repo for
the original codec/UI this was adapted from, and for
data/dave/item_names.json's provenance (data/dave/README.md here has the
short version).

Unlike Octopath's GVAS binary format, once decoded this is plain JSON -
so, like Duckov, everything in it is safely editable through cedit's
generic tree editor. No read_only_check is needed here.
"""
import json
import os
import subprocess
from pathlib import Path

from lib.base import GameProfile

_KEY = [ord(c) for c in "GameData"]


def _xor_units(units):
    n = len(_KEY)
    return [u ^ _KEY[i % n] for i, u in enumerate(units)]


def _loads(raw_bytes):
    enc_str = raw_bytes.decode("utf-8")
    units = [ord(c) for c in enc_str]
    plain_units = _xor_units(units)
    text = "".join(chr(u) for u in plain_units)
    return json.loads(text)


def _dumps(data):
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    units = [ord(c) for c in text]
    cipher_units = _xor_units(units)
    return "".join(chr(u) for u in cipher_units).encode("utf-8")


# ---------------------------------------------------------- save location
#
# discover_saves() (lib/base.py) already walks these recursively and
# matches file_patterns' glob against every file it finds, so it covers
# both the flat SData layout and SteamSData's per-Steam-id subfolders
# without any extra code here.

_APP_SUPPORT = Path.home() / "Library" / "Application Support"
DEFAULT_SAVE_DIRS = [
    str(_APP_SUPPORT / "nexon" / "DAVE THE DIVER" / "SteamSData"),
    str(_APP_SUPPORT / "nexon" / "DAVE THE DIVER" / "SData"),
    str(_APP_SUPPORT / "com.nexon.dave" / "SteamSData"),
]

# These are C# `int` (Int32) in the game's PlayerInfo/DLC save structs -
# not enforced as a hard clamp here (cedit's generic quick-edit doesn't do
# per-field bounds), just documented so a value typed in stays sane.
_INT32_MAX = 2_147_483_647

QUICK_FIELDS = {
    "Gold": ["PlayerInfo", "m_Gold"],
    "Bei": ["PlayerInfo", "m_Bei"],
    "Artisan's Flame": ["PlayerInfo", "m_ChefFlame"],
    "Research Points": ["PlayerInfo", "m_researchPoint"],
    "Trust Points": ["PlayerInfo", "m_trustPoint"],
    "Fake Points": ["PlayerInfo", "m_FakePoint"],
    "Jungle Gold": ["JDLCContents", "junglePlayerInfoSave", "jungleGold"],
    "Jungle Flame": ["JDLCContents", "junglePlayerInfoSave", "jungleChefFlame"],
}


# --------------------------------------------------------- pre-save guard
#
# The game holds its own save state in memory and rewrites its autosave
# file periodically. If it's running (or gets launched) around the time
# cedit writes a save, the game's next autosave silently overwrites the
# edit with its own pre-edit in-memory state - which looks like "my
# change got reset" even though the write itself succeeded. Block saving
# outright rather than let that surprise happen quietly.

def _is_game_running():
    try:
        out = subprocess.run(
            ["ps", "-axo", "comm="], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        return False
    for line in out.splitlines():
        low = line.lower()
        if "dave" in low and "diver" in low:
            return True
    return False


def _is_file_open(path):
    if not os.path.exists(path):
        return False
    try:
        out = subprocess.run(
            ["lsof", "-t", path], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        return False
    return bool(out.strip())


def _pre_save_check(path):
    if _is_game_running():
        return (
            "Dave the Diver appears to be running. Quit the game fully "
            "(⌘Q) before saving - a running game overwrites your "
            "edits on its next autosave."
        )
    if _is_file_open(path):
        return (
            "The save file is currently open by another process. If you "
            "just quit the game, wait a moment and try again."
        )
    return None


PROFILE = GameProfile(
    key="dave",
    display_name="Dave the Diver",
    default_save_dirs=DEFAULT_SAVE_DIRS,
    file_patterns=[("Save files (*_GD.sav)", "*_GD.sav"), ("All files", "*.*")],
    quick_fields=QUICK_FIELDS,
    loads=_loads,
    dumps=_dumps,
    binary=True,
    pre_save_check=_pre_save_check,
    notes=(
        "Currency/point fields are C# Int32 in the game's own save structs, "
        "so keep them under 2,147,483,647. Materials (save key: "
        "Ingredients, keyed by ingredient id) and Items (save key: "
        "InventoryItemSlot, keyed by a GUID) are dict-of-dicts, not "
        "list-of-dicts, so they show as an expandable tree node rather "
        "than a table - edit an entry's count field directly, or add a "
        "new key/entry for a brand-new item id via Add Key to Selected. "
        "Item/ingredient names for the id you're looking at aren't shown "
        "inline; cross-reference against data/dave/item_names.json (see "
        "data/dave/README.md - coverage is complete for cooking "
        "materials but incomplete for weapon/gear item ids) or a "
        "wiki/datamine. Saving is blocked outright while the game process "
        "appears to be running, or while the save file is held open by "
        "another process - fully quit the game (⌘Q) first, since its "
        "next autosave would otherwise silently overwrite your edit. "
        "Leave the game closed for a bit after saving too: relaunching "
        "before Steam Cloud sync catches up can pull an older cloud copy "
        "back over your edit."
    ),
)
