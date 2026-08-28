"""
DREDGE support for cedit.

DREDGE's save is a .NET BinaryFormatter blob that only the game's own
compiled types can deserialize/reserialize - there is no way to parse it in
pure Python. So unlike every other game profile, this one does not implement
loads/dumps at all: it sets `custom_launcher`, which opens its own window
that talks to lib/dredge_client.py, which in turn shells out to the
vendored C# bridge in lib/dredge_bridge/ (adapted from AppleBoiy/dredge-se).
That bridge does the real load -> patch -> verify -> backup -> atomic-replace
work; the window (games/dredge_window.py) only builds the patch and shows
what changed.

Scope (per project decision): primitives (decimal/int/float/string/bool
save variables) plus full inventory grid editing - move, remove, duplicate,
and spawn (spawn only works once you've dropped a real item catalog into
data/dredge/manifest.json; see that folder's README).

Requires a local .NET SDK and a local DREDGE install (for its Managed/
Assembly-CSharp.dll) - this is unusable without both, which is expected:
there's no such thing as a portable DREDGE save editor.

This module deliberately stays free of any PySide6 import - the actual
window (all the Qt-dependent code) lives in games/dredge_window.py instead,
imported lazily inside launch() below, only once a window is actually about
to open. That keeps `import games` (and therefore the CLI, tests, and
anything else that just wants a GameProfile to call loads/dumps/spawn_item
on) usable without PySide6 installed at all - custom_launcher is the one
GameProfile feature that can never be scripted headlessly anyway (DREDGE
has no loads/dumps to call), so there's nothing lost by deferring it.
"""

from lib.base import GameProfile


def launch(parent):
    from games.dredge_window import launch as _launch
    _launch(parent)


PROFILE = GameProfile(
    key="dredge",
    display_name="DREDGE",
    default_save_dirs=[],
    file_patterns=[("DREDGE save files", "*.bin"), ("All files", "*.*")],
    quick_fields={},
    custom_launcher=launch,
    notes=(
        "DREDGE saves are .NET BinaryFormatter blobs - editing them requires a local "
        ".NET SDK and a local DREDGE install (its Managed/Assembly-CSharp.dll). This opens "
        "its own window backed by lib/dredge_client.py + the vendored dotnet bridge."
    ),
)
