"""
cedit game profile: BlazBlue Entropy Effect (Steam)

Save format: a slot file (named just a digit "1".."9", no extension)
holding an LZ4-framed schema-less protobuf message. Ported from
https://github.com/AppleBoiy/bbee-se (MIT licensed) - lib/bbee_wire.py and
lib/bbee_lib.py are that project's own wire-format reader and currency
locator/editor, essentially unchanged; see their module docstrings.

Deliberately narrow scope, matching bbee-se's own README exactly: the
only thing this profile can read AND write is persistent Analysis Points
(currency id 1 inside ModelPlayerNewCurrencyPack). Everything else in the
save - per-run Exchange Points, other currencies, unlock flags, story
progression, online/co-op state - is neither parsed nor exposed, not even
read-only, because the wire format has no field names (a schema-less
protobuf message only has numbered fields) - showing raw numbered fields
in the tree would just be confusing, and none of them are safe to write
back anyway. bbee-se's own README explains the reasoning: "This
deliberately narrow boundary avoids guessing at unknown progression
fields." This port keeps exactly that boundary rather than widening it.

Every write re-decompresses the ORIGINAL on-disk bytes fresh (never the
in-memory dict's own bookkeeping) before editing, then re-decompresses and
re-parses the freshly-compressed output to confirm the new Analysis
Points value actually reads back correctly - the same "reparse and
verify" step bbee-se's own apply() does before replacing the file.

Needs the `lz4` command-line tool (see lib/bbee_lib.py) - `brew install
lz4` on macOS, or set BBEE_LZ4 to its path if it's somewhere unusual.
"""
from pathlib import Path

from lib.base import GameProfile
from lib import bbee_lib


class BbeeData(dict):
    """The parsed (narrow) view of a save, plus the original on-disk LZ4
    bytes needed to reconstruct the edit (kept as a plain attribute so it
    doesn't show up as a dict key/tree node) - same convention as
    games/octopath.py's OctopathData."""
    pass


def loads(raw_bytes):
    decoded = bbee_lib.decompress_bytes(raw_bytes)
    info = bbee_lib.inspect_decoded(decoded, raw_size=len(raw_bytes))
    wrapped = BbeeData({
        "AnalysisPoints": info.ap,
        "_model_count": info.model_count,
        "_raw_size": info.raw_size,
        "_decoded_size": info.decoded_size,
    })
    wrapped._raw = bytes(raw_bytes)
    return wrapped


def dumps(data):
    if not isinstance(data, BbeeData) or not hasattr(data, "_raw"):
        raise ValueError(
            "This save wasn't loaded through cedit's BlazBlue Entropy Effect "
            "profile (missing original file bytes) - reload the file and try again."
        )
    new_ap = data.get("AnalysisPoints")
    if not isinstance(new_ap, int) or isinstance(new_ap, bool):
        raise ValueError("Analysis Points must be a whole number")

    # A fresh, pristine reparse of the ORIGINAL bytes - never derived from
    # the in-memory dict, which a raw-JSON paste could otherwise have
    # mutated in ways that don't correspond to a real save (e.g. an
    # edited _model_count that isn't actually true of the real protobuf).
    decoded = bbee_lib.decompress_bytes(data._raw)
    edited_decoded = bbee_lib.edit_ap(decoded, new_ap)
    compressed = bbee_lib.compress_to_bytes(edited_decoded)

    # Re-decompress and re-parse the just-written bytes to confirm the
    # edit actually reads back correctly before cedit ever writes this to
    # disk - mirrors bbee-se's own apply()'s temp-file reparse-and-verify.
    verify = bbee_lib.inspect_decoded(bbee_lib.decompress_bytes(compressed))
    if verify.ap != new_ap:
        raise ValueError(
            "Verification failed: the freshly compressed save did not read "
            "back with the expected Analysis Points value. Nothing was saved."
        )
    return compressed


def read_only_check(container, key, value):
    if isinstance(key, str) and key.startswith("_"):
        return True  # informational bookkeeping only, see loads()
    return key != "AnalysisPoints"  # the only field this profile can ever write


DEFAULT_SAVE_DIRS = [
    "~/Library/Application Support/91Act/BlazBlueEntropyEffect/Steam",
    "~/AppData/LocalLow/91Act/BlazBlueEntropyEffect/Steam",
]

PROFILE = GameProfile(
    key="bbee",
    display_name="BlazBlue Entropy Effect",
    default_save_dirs=[str(Path(p).expanduser()) for p in DEFAULT_SAVE_DIRS],
    # Save slot files are named just a single digit (1-9), no extension -
    # discover_saves()'s recursive walk handles the <account-id>/Save/
    # nesting on its own, same as Dave the Diver's SteamSData layout.
    file_patterns=[("Save slot", "[1-9]")],
    quick_fields={"Analysis Points": ["AnalysisPoints"]},
    loads=loads,
    dumps=dumps,
    binary=True,
    read_only_check=read_only_check,
    notes=(
        "Only persistent Analysis Points (AP) - currency id 1 inside "
        "ModelPlayerNewCurrencyPack - is readable or writable here; "
        "everything else in the save is a schema-less protobuf field with "
        "no name to show, so it isn't parsed or exposed at all (matches "
        "bbee-se's own deliberately narrow scope: per-run Exchange Points, "
        "other currencies, unlock flags, and story/online progression are "
        "all left untouched). AP must be a whole number from 0 to "
        "99,999,999. Requires the `lz4` command-line tool on PATH (`brew "
        "install lz4` on macOS) - set the BBEE_LZ4 environment variable if "
        "it's somewhere unusual. Quit the game (and let Steam Cloud settle) "
        "before editing - a running game or an in-progress cloud sync can "
        "overwrite your edit the same way it can for any other game here."
    ),
)
