"""
cedit - shared utilities and the GameProfile plugin contract.

Folder layout (see cedit.py's own docstring too):
  games/  - one module per game, each exposing `PROFILE = GameProfile(...)`
  lib/    - this file, plus any game's own parsing library too unusual to
            be config-driven (e.g. lib/octopath_lib.py)
  data/   - per-game data/config files a games/<name>.py loads at import time

A GameProfile describes:
  - where its save files usually live and what they're named (config)
  - how to parse a save file's text into Python data, and back (format)
  - which fields deserve a "Quick Edit" shortcut
  - any special/packed data fields that need custom decode/encode instead
    of being shown as a raw string (special data)

Most games' "config / format / special data" is plain data, not code, so
each game should normally be a JSON file under data/ (data/<name>.json)
loaded with `GameProfile.from_config(...)`:

    {
      "key": "yourgame",
      "display_name": "Your Game",
      "default_save_dirs": ["~/Library/Application Support/YourGame/Saves"],
      "file_patterns": [["Save files", "*.json"], ["All files", "*.*"]],
      "quick_fields": {"Gold": ["player", "gold"]},
      "json_quirks": [{"pattern": "...", "replacement": "..."}],
      "packed_value_node": {
        "type_field": "dataType", "data_field": "data", "key_field": "key",
        "codecs": {"1": "float32le", "2": "int32le", "3": "bool8", "4": "utf8"}
      },
      "notes": "Anything worth telling the person editing this save."
    }

and a two-line games/<name>.py that just points at it:

    import os
    from lib.base import GameProfile
    PROFILE = GameProfile.from_config(
        os.path.join(os.path.dirname(__file__), "..", "data", "yourgame.json")
    )

Only a genuinely unusual save format (real encryption, a bespoke binary
layout, a checksum that must be recalculated) needs actual Python - pass a
custom `loads`/`dumps` pair or extra `SpecialNode`s to `from_config(...)`,
or (as games/octopath.py does) skip from_config entirely and build a
GameProfile by hand. The core editor (cedit.py) only ever talks to a
GameProfile object; it has no per-game logic in it at all.
"""

import os
import re
import json
import base64
import fnmatch
import struct
import shutil
import datetime
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple


# ------------------------------------------------------------ window sizing
#
# Plain (width, height) tuples, not Qt calls, so this stays importable
# without PySide6 (games/*.py's own tests, lib/dredge_client.py, etc. don't
# need a display). cedit.py and every custom_launcher window should pull
# their resize()/setMinimumSize() from here instead of picking their own
# numbers, so windows across the app share one sizing convention instead of
# each guessing independently:
#
#   self.resize(*MAIN_WINDOW_SIZE)          # or GAME_WINDOW_SIZE
#   self.setMinimumSize(*MAIN_WINDOW_MIN)   # or GAME_WINDOW_MIN
#
# MAIN_WINDOW_* is for cedit.py's own generic editor window.
# GAME_WINDOW_* is for a custom_launcher's own window (see DREDGE) - bigger
# by default since those tend to host a canvas/graphics view alongside a
# list, not just a tree + text panel.
MAIN_WINDOW_SIZE = (1300, 780)
MAIN_WINDOW_MIN = (760, 480)
GAME_WINDOW_SIZE = (1150, 700)
GAME_WINDOW_MIN = (800, 520)


# ---------------------------------------------------------------- file IO

def backup_file(path):
    """Write a timestamped backup next to the original file. Returns the
    backup path."""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{path}.{ts}.bak"
    shutil.copy2(path, backup_path)
    return backup_path


def atomic_write_bytes(path, data):
    """Write bytes to path atomically (write temp file, then replace)."""
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmpsave_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def atomic_write_text(path, text):
    """Write text to path atomically (write temp file, then replace)."""
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmpsave_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# ------------------------------------------------------------- value types

def guess_type(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if value is None:
        return "null"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "?"


def smart_parse(raw_text):
    """Best-effort guess of what type a freshly-typed string should become."""
    s = raw_text.strip()
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "none"):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return raw_text


def coerce_value(raw_text, original_value):
    """Convert a string the user typed back into the right Python type,
    based on what type the value originally was."""
    t = guess_type(original_value)
    if t == "bool":
        low = raw_text.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
        raise ValueError("Expected true/false")
    if t == "int":
        return int(raw_text.strip())
    if t == "float":
        return float(raw_text.strip())
    if t == "null":
        if raw_text.strip().lower() in ("null", "none", ""):
            return None
        return smart_parse(raw_text)
    if t == "str":
        return raw_text
    raise ValueError(f"Cannot edit a value of type '{t}' directly here")


def get_by_path(data, path):
    """Walk a list of dict keys / list indexes, returning the value or
    raising KeyError/IndexError/TypeError if the path doesn't exist."""
    cur = data
    for part in path:
        cur = cur[part]
    return cur


def set_by_path(data, path, value):
    cur = data
    for part in path[:-1]:
        cur = cur[part]
    cur[path[-1]] = value


# ------------------------------------------- generic packed-value codecs
#
# A lot of game save formats attach typed binary blobs to items/entities -
# "here's a dict with a type code and a base64 byte string". Rather than
# writing custom decode/encode Python for every game that does this, games
# can just declare which type codes map to which of these common codecs.

def _decode_float32le(raw):
    return struct.unpack("<f", raw)[0] if len(raw) == 4 else 0.0


def _encode_float32le(value):
    return struct.pack("<f", float(value))


def _decode_int32le(raw):
    return struct.unpack("<i", raw)[0] if len(raw) == 4 else 0


def _encode_int32le(value):
    return struct.pack("<i", int(float(value)))


def _decode_bool8(raw):
    return bool(raw[0]) if raw else False


def _encode_bool8(value):
    low = str(value).strip().lower()
    return bytes([1 if low in ("1", "true", "yes") else 0])


def _decode_utf8(raw):
    return raw.decode("utf-8", errors="replace")


def _encode_utf8(value):
    return str(value).encode("utf-8")


PACKED_VALUE_CODECS = {
    "float32le": (_decode_float32le, _encode_float32le),
    "int32le": (_decode_int32le, _encode_int32le),
    "bool8": (_decode_bool8, _encode_bool8),
    "utf8": (_decode_utf8, _encode_utf8),
}


def make_base64_packed_node(codec_by_type, name="packed", key_field="key",
                             type_field="dataType", data_field="data"):
    """Build a SpecialNode for the common "dict with a type code and a
    base64-packed byte blob" pattern, e.g.
    {"key": "BulletCount", "dataType": 2, "data": "HgAAAA=="}.

    codec_by_type maps the type code (as it appears in the parsed JSON,
    usually an int) to a codec name in PACKED_VALUE_CODECS.
    """

    def is_match_dict(d):
        return isinstance(d, dict) and type_field in d and data_field in d and key_field in d

    def matches(container, key, value):
        return key == data_field and is_match_dict(container)

    def decode(container, key, value):
        type_code = container.get(type_field)
        codec_name = codec_by_type.get(type_code)
        if codec_name is None:
            return value  # unrecognized type code - leave the raw value alone
        raw = base64.b64decode(value) if value else b""
        decode_fn, _ = PACKED_VALUE_CODECS[codec_name]
        return decode_fn(raw)

    def encode(container, key, new_value):
        type_code = container.get(type_field)
        codec_name = codec_by_type.get(type_code)
        if codec_name is None:
            raise ValueError(f"No codec configured for type code {type_code!r}")
        _, encode_fn = PACKED_VALUE_CODECS[codec_name]
        raw = encode_fn(new_value)
        return base64.b64encode(raw).decode("ascii")

    def type_label(container, key, value):
        type_code = container.get(type_field)
        codec_name = codec_by_type.get(type_code, f"type{type_code}")
        return f"{name}:{codec_name}"

    return SpecialNode(name=name, matches=matches, decode=decode, encode=encode, type_label=type_label)


# --------------------------------------- generic "almost-JSON" quirk fixes
#
# Some save formats are 99% valid JSON with one or two known, fixed
# formatting bugs from whatever serializer wrote them. Rather than writing
# a custom parser per game, a game can just declare regex fix-ups applied
# before json.loads.

def apply_text_quirks(raw_text, quirks):
    """quirks: a list of {"pattern": <regex str>, "replacement": <repl str>}
    dicts, applied in order with re.sub."""
    text = raw_text
    for quirk in quirks or []:
        text = re.sub(quirk["pattern"], quirk["replacement"], text)
    return text


def make_json_loader(quirks=None):
    def loader(raw_text):
        return json.loads(apply_text_quirks(raw_text, quirks))
    return loader


def make_json_dumper(indent=2):
    def dumper(data):
        return json.dumps(data, indent=indent, ensure_ascii=False)
    return dumper


# -------------------------------------------------------- plugin contract

@dataclass
class SpecialNode:
    """A pluggable hook that lets a game profile show/edit a node's raw
    value in a custom decoded form - e.g. a base64-packed float, an
    encrypted string, a packed bitfield - instead of the raw JSON value.

    matches(container, key, value) -> bool
        Return True if this node (a dict's `key: value` pair, or a list's
        `index: value` pair) should use this handler.

    decode(container, key, value) -> Any
        Return the human-friendly value to display and edit.

    encode(container, key, new_decoded_value) -> Any
        Given a new value the user typed (already a plain str), return the
        raw value that should actually be stored back at `container[key]`.

    type_label(container, key, value) -> str
        Optional: a short string for the tree's "Type" column, e.g.
        "item:int". Defaults to the handler's name.
    """

    name: str
    matches: Callable[[Any, Any, Any], bool]
    decode: Callable[[Any, Any, Any], Any]
    encode: Callable[[Any, Any, Any], Any]
    type_label: Optional[Callable[[Any, Any, Any], str]] = None

    def label_for(self, container, key, value):
        if self.type_label:
            return self.type_label(container, key, value)
        return self.name


@dataclass
class GameProfile:
    """Everything the generic cedit editor needs to know to load, edit,
    and save one specific game's save files."""

    key: str                      # short id, e.g. "duckov" - used internally
    display_name: str             # shown in the game picker, e.g. "Escape from Duckov"
    default_save_dirs: List[str]  # candidate folders to look in first
    file_patterns: List[Tuple[str, str]]  # [(label, glob), ...] for the Open dialog
    quick_fields: dict            # {"Money": ["EconomyData", "value", "money"], ...}
    loads: Callable[[str], Any] = json.loads
    dumps: Optional[Callable[[Any], str]] = None  # None -> default json.dumps(indent=2)
    special_nodes: List[SpecialNode] = field(default_factory=list)
    notes: str = ""                # freeform tips shown in the UI (file names, gotchas)
    binary: bool = False           # True: read/write the file as bytes, not text
    read_only_check: Optional[Callable[[Any, Any, Any], bool]] = None
    # read_only_check(container, key, value) -> True blocks editing that node
    # in the tree (double-click shows a message instead). Use this when a
    # format's full parsed structure is worth browsing but only a narrow,
    # well-understood subset of it is safe to write back (see games/octopath.py).
    custom_launcher: Optional[Callable[[Any], None]] = None
    # custom_launcher(parent) -> None. Set this instead of loads/dumps when a
    # game's save model genuinely doesn't fit "read whole file -> edit tree
    # -> write whole file back" - e.g. DREDGE, where the only legal way to
    # touch the save is a subprocess bridge that does its own load/patch/
    # verify/backup/replace. When set, selecting this game in cedit.py opens
    # a dedicated window (built by custom_launcher) instead of the generic
    # tree editor; quick_fields/special_nodes/loads/dumps are unused.
    #
    # `parent` is the main SaveEditorWindow (a QWidget) - a custom_launcher
    # normally builds a QDialog/QMainWindow with `parent` passed as its Qt
    # parent (so it closes/minimizes with the main window and gets a native
    # window manager relationship), e.g.:
    #
    #   def launch(parent):
    #       DredgeEditorWindow(parent).show()

    def dump(self, data):
        if self.dumps:
            return self.dumps(data)
        return json.dumps(data, indent=2, ensure_ascii=False)

    def find_special_node(self, container, key, value):
        for node in self.special_nodes:
            try:
                if node.matches(container, key, value):
                    return node
            except Exception:
                continue
        return None

    def is_read_only(self, container, key, value):
        if self.read_only_check is None:
            return False
        try:
            return bool(self.read_only_check(container, key, value))
        except Exception:
            return False

    def find_default_save_dir(self):
        for d in self.default_save_dirs:
            if d and os.path.isdir(d):
                return d
        return None

    def discover_saves(self, limit=200):
        """Recursively scan default_save_dirs for files matching
        file_patterns' globs (skipping the catch-all "*.*" entry), most
        recently modified first - the equivalent of DREDGE's own
        lib.dredge_client.discover_saves() for every config-driven game.

        Recursive because a save's real location is often nested deeper
        than the configured default dir (e.g. Octopath Traveler's saves
        live under .../Octopath_Traveler/<steam id>/SaveGames/*.sav, not
        directly in .../Octopath_Traveler itself). Best-effort: a
        permission error or similar on any one subdirectory is skipped
        rather than aborting the whole scan."""
        patterns = [
            part for _label, glob_str in self.file_patterns
            for part in glob_str.split() if part != "*.*"
        ]
        if not patterns:
            return []
        found = set()
        for base in self.default_save_dirs:
            if not base or not os.path.isdir(base):
                continue
            for root, _dirs, files in os.walk(base, onerror=lambda e: None):
                for name in files:
                    if any(fnmatch.fnmatch(name, pat) for pat in patterns):
                        found.add(os.path.join(root, name))
        def _mtime(path):
            try:
                return os.path.getmtime(path)
            except OSError:
                return 0
        return sorted(found, key=_mtime, reverse=True)[:limit]

    @classmethod
    def from_config(cls, config_path, *, extra_special_nodes=None,
                     custom_loads=None, custom_dumps=None):
        """Build a GameProfile from a declarative JSON config file (see the
        module docstring above for the shape). Pass custom_loads/dumps or
        extra_special_nodes only for a format quirk too unusual to express
        as data (real encryption, a bespoke binary layout, etc)."""
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)

        default_save_dirs = [
            os.path.expanduser(os.path.expandvars(p))
            for p in cfg.get("default_save_dirs", [])
        ]
        file_patterns = [tuple(p) for p in cfg.get("file_patterns", [["All files", "*.*"]])]

        special_nodes = list(extra_special_nodes or [])
        pv = cfg.get("packed_value_node")
        if pv:
            codec_by_type = {}
            for raw_key, codec_name in pv.get("codecs", {}).items():
                # JSON object keys are always strings; type codes in the
                # parsed save data are usually ints, so convert numeric
                # keys back to int so lookups against parsed data match.
                key = int(raw_key) if isinstance(raw_key, str) and raw_key.lstrip("-").isdigit() else raw_key
                codec_by_type[key] = codec_name
            special_nodes.append(make_base64_packed_node(
                codec_by_type=codec_by_type,
                name=pv.get("name", "packed"),
                key_field=pv.get("key_field", "key"),
                type_field=pv.get("type_field", "dataType"),
                data_field=pv.get("data_field", "data"),
            ))

        loads_fn = custom_loads or make_json_loader(cfg.get("json_quirks"))
        dumps_fn = custom_dumps or make_json_dumper(cfg.get("json_indent", 2))

        return cls(
            key=cfg["key"],
            display_name=cfg["display_name"],
            default_save_dirs=default_save_dirs,
            file_patterns=file_patterns,
            quick_fields=cfg.get("quick_fields", {}),
            loads=loads_fn,
            dumps=dumps_fn,
            special_nodes=special_nodes,
            notes=cfg.get("notes", ""),
        )
