"""
cedit game profile: Octopath Traveler / Octopath Traveler II

Save format: GVAS (Unreal Engine 4.27's SaveGame binary layout), the same
for both games (save class "KSSaveGameBP_C"); which one a given file is
gets auto-detected from its contents (lib/octopath_lib.py: detect_game).

This is fundamentally different from Duckov's plain-JSON saves, so unlike
games/duckov.py this profile is NOT config-driven - GameProfile.binary=True
and custom loads/dumps are exactly the "genuinely unusual format" escape
hatch the lib/base.py module docstring describes.

Parsing (browsing) vs. writing (editing) have deliberately different scope
here:

  - Parsing (lib/octopath_lib.py, adapted from AppleBoiy/octopath-save-
    editor, GPL-3.0) reads the WHOLE save: money, starting traveler, all 8
    characters' stats/bonuses/jobs/equipment, full inventory, and (OT1) the
    tame-monster Capture roster. All of it is browsable in cedit's tree.

  - Writing only covers money, the starting traveler, and each character's
    core stats and stat bonuses (level, EXP, HP/MP, job points, all eight
    bonus stats) - the fields with a fixed byte offset that never depends
    on any other data, so no item/monster catalog validation is needed to
    write them back safely. Equipment, inventory, and the Capture roster
    are shown read-only for now: changing which item occupies a slot, or
    adding a new inventory stack, involves either slot-category validation
    or empty-slot allocation logic (see the upstream project's
    normalize_edits/apply_edits) that hasn't been ported here yet.

  read_only_check() below is what enforces that split: it blocks every
  field outside the writable set from being edited in the tree at all,
  rather than silently discarding an edit the "Save" step doesn't know
  how to write back.

Every write re-parses the result and checks it matches what was intended
before returning it, mirroring the upstream project's own verify-before-
write discipline (see dumps() below).
"""

import os
import struct

from lib.base import GameProfile
from lib import octopath_lib as octo_lib


DEFAULT_SAVE_DIRS = [
    "~/Documents/My Games/Octopath_Traveler",
    "~/Documents/My Games/Octopath_Traveler2",
    "~/Documents/My Games/Octopath_Traveler/Steam",
    "~/Documents/My Games/Octopath_Traveler2/Steam",
    "~/OneDrive/Documents/My Games/Octopath_Traveler",
    "~/OneDrive/Documents/My Games/Octopath_Traveler2",
]


class OctopathData(dict):
    """The parsed save (games/octopath_lib.parse_save output), plus the
    original file bytes needed to patch edits back in (kept as a plain
    instance attribute so it doesn't show up as a dict key/tree node)."""
    pass


def loads(raw_bytes):
    data = octo_lib.parse_save(raw_bytes)
    wrapped = OctopathData(data)
    wrapped._raw = bytes(raw_bytes)
    return wrapped


# Character fields safe to write back: exactly the stat/bonus fields
# lib/octopath_lib.parse_save records a fixed offset for. Job IDs and
# equipment have offsets too, but are excluded here (see module docstring).
_EDITABLE_CHARACTER_FIELDS = frozenset(octo_lib.CHARACTER_PROPERTIES.keys())
_EDITABLE_ROOT_FIELDS = frozenset({"money", "hero"})


def _looks_like_root(container):
    return (
        isinstance(container, dict)
        and "money" in container and "hero" in container and "characters" in container
    )


def _looks_like_character_row(container):
    return (
        isinstance(container, dict)
        and "id" in container and "name" in container
        and "level" in container and "equipment" in container
    )


def read_only_check(container, key, value):
    if isinstance(key, str) and key.startswith("_"):
        return True  # offset bookkeeping and other internals
    if _looks_like_root(container):
        return key not in _EDITABLE_ROOT_FIELDS
    if _looks_like_character_row(container):
        return key not in _EDITABLE_CHARACTER_FIELDS
    # Equipment slots, inventory entries, capture slots, job names, etc:
    # fully browsable, not yet safe to write back (see module docstring).
    return True


def _check_bounds(field, value):
    limits = octo_lib.FIELD_LIMITS.get(field)
    if limits is None:
        return
    lo, hi = limits
    if not lo <= value <= hi:
        raise ValueError(f"{field} must be between {lo:,} and {hi:,} (got {value:,})")


def dumps(data):
    if not isinstance(data, OctopathData) or not hasattr(data, "_raw"):
        raise ValueError(
            "This save wasn't loaded through cedit's Octopath profile (missing "
            "original file bytes) - reload the file and try again."
        )

    raw = bytearray(data._raw)

    money = int(data["money"])
    hero = int(data["hero"])
    _check_bounds("money", money)
    _check_bounds("hero", hero)
    struct.pack_into("<I", raw, data["_offsets"]["money"], money)
    struct.pack_into("<I", raw, data["_offsets"]["hero"], hero)

    for row in data["characters"]:
        for field, offset in row.get("_offsets", {}).items():
            if field == "second_job_id" or field not in _EDITABLE_CHARACTER_FIELDS:
                continue  # not writable in cedit yet - never repacked
            value = row.get(field)
            if value is None:
                continue
            value = int(value)
            _check_bounds(field, value)
            struct.pack_into("<I", raw, offset, value)

    new_bytes = bytes(raw)

    # Verify before handing back: re-parse the patched bytes and confirm
    # every field we just wrote reads back exactly as intended.
    try:
        verify = octo_lib.parse_save(new_bytes)
    except octo_lib.SaveError as e:
        raise ValueError(f"Post-write verification failed to parse the result: {e}")

    if verify["money"] != money:
        raise ValueError("Post-write verification failed for money")
    if verify["hero"] != hero:
        raise ValueError("Post-write verification failed for the starting traveler")

    verify_by_id = {row["id"]: row for row in verify["characters"]}
    for row in data["characters"]:
        vrow = verify_by_id.get(row["id"])
        for field in row.get("_offsets", {}):
            if field == "second_job_id" or field not in _EDITABLE_CHARACTER_FIELDS:
                continue
            expected = row.get(field)
            if expected is None:
                continue
            if vrow is None or vrow.get(field) != int(expected):
                raise ValueError(f"Post-write verification failed for {row['name']} - {field}")

    return new_bytes


PROFILE = GameProfile(
    key="octopath",
    display_name="Octopath Traveler / II",
    default_save_dirs=[os.path.expanduser(p) for p in DEFAULT_SAVE_DIRS],
    file_patterns=[("Octopath save files", "*.sav"), ("All files", "*.*")],
    quick_fields={
        "Money": ["money"],
        "Starting Traveler (1-8)": ["hero"],
    },
    loads=loads,
    dumps=dumps,
    binary=True,
    read_only_check=read_only_check,
    notes=(
        "Auto-detects Octopath Traveler vs. Octopath Traveler II from the save "
        "itself. Editable: money, starting traveler, and each character's "
        "level/EXP/HP/MP/job points/stat bonuses (double-click inside "
        "'characters' in the tree). Equipment, inventory, and the Capture "
        "roster are browsable but read-only for now.\n"
        "Item/monster names show as 'Unknown item/monster <id>' until the real "
        "catalogs from the upstream project's static/ folder are dropped into "
        "data/octopath/ (see the README.md there)."
    ),
)
