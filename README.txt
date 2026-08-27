cedit - a save editor for several games
========================================

("cedit", from "c-save-game-editor")

A PySide6 (Qt) GUI save editor built around one idea: each game's save
format, file locations, and quirks live entirely in their own "profile"
under games/, and the editor itself (cedit.py) is 100% generic. Adding a
new game never requires touching cedit.py.

(Originally built on Tkinter; migrated to PySide6 because Homebrew's
current Tcl/Tk 9.x has real Aqua-rendering performance problems on macOS
that aren't fixable from application code. PySide6 ships its own Qt build
via a normal pip install, sidestepping that entirely.)

Currently supported:
  - Escape from Duckov       (games/duckov.py + data/duckov.json)
  - Octopath Traveler / II   (games/octopath.py + lib/octopath_lib.py)
  - DREDGE                   (games/dredge.py + lib/dredge_client.py)


RUNNING IT
----------
    pip install -r requirements.txt   # installs PySide6
    python3 cedit.py
    python3 cedit.py --game duckov /path/to/Save_1.sav

Requires Python 3 and PySide6 (`pip install PySide6`). No separate system
package needed - PySide6 bundles its own Qt build, unlike Tkinter which
depends on whatever Tcl/Tk your Python happens to be linked against.


FOLDER LAYOUT
-------------
    cedit.py    - the generic editor: menus, tree view, quick-edit panel,
                  raw JSON preview, file I/O. Has no per-game logic at all.
    games/      - one module per game, each exporting a `PROFILE` object
                  (see lib/base.py's GameProfile for the contract).
    lib/        - lib/base.py (the shared plugin contract + utilities) plus
                  any game's own parsing code too unusual to be pure config
                  (lib/octopath_lib.py, lib/dredge_client.py).
    data/       - per-game config/data files a games/<name>.py loads at
                  import time (data/duckov.json, data/octopath/*.json,
                  data/dredge/*.json).


PER-GAME NOTES
---------------

Escape from Duckov
  Plain-JSON Unity Easy Save 3 format, fully editable through the generic
  tree editor. No extra setup needed.

Octopath Traveler / II
  Unreal Engine 4.27 GVAS binary saves, parsed by byte-offset scanning
  (see lib/octopath_lib.py). Writable: money, starting traveler, each
  character's stat fields, which item occupies an equipment slot (checked
  against the item catalog's category), an inventory item's count (only
  for items the catalog marks non-progression-linked - also works to add a
  brand-new item into any still-empty inventory slot), and (OT1) each
  Capture slot's monster/count/caught flag. Not supported: second-job
  assignment, and adding entirely new Capture slots (the save always has a
  fixed number of them). Item/monster names need the catalogs in
  data/octopath/ - see data/octopath/README.md if they ever go missing or
  get swapped for the wrong file (items.json and item-details.json in your
  own octopath-save-editor repo have similar names but different schemas -
  easy to mix up).

DREDGE
  DREDGE saves are .NET BinaryFormatter blobs that only the game's own
  compiled types can (de)serialize - there's no way to parse them in pure
  Python. So this profile doesn't implement loads/dumps at all: it opens
  its own window (games/dredge.py) that shells out to a small vendored C#
  bridge (lib/dredge_bridge/) which loads DREDGE's own Assembly-CSharp.dll
  via reflection to do the real read/patch/verify/backup/write. This
  needs, on your machine:
    - a .NET SDK (the bridge is built automatically on first use)
    - a local DREDGE install, for its Managed/Assembly-CSharp.dll
  Supports editing save variables and full inventory-grid editing (move,
  remove, duplicate, spawn) with real collision/available-space checking.
  That last part - and item names instead of raw ids - needs a generated
  data/dredge/manifest.json; see data/dredge/README.md for how to make one
  from your own local install.


SAFETY
------
Every write path (generic text/binary writer in cedit.py, and the DREDGE
bridge's own edit command) makes a timestamped backup of the original file
before touching it, and verifies the newly written file re-parses cleanly
before replacing the original. Nothing is overwritten silently.


TESTS
-----
    python3 -m unittest discover -s tests -v

Covers the toolkit-agnostic logic in lib/base.py and lib/dredge_client.py
(value coercion, path get/set, packed-value codecs, GameProfile config
loading and save discovery, DREDGE grid/cell validation and inventory-op
validation). No PySide6/display needed to run these. The PySide6 UI itself
(cedit.py, games/dredge.py) has no automated test coverage - it needs a
real display to exercise, so verify it by running the app.


BUILD ARTIFACTS
----------------
lib/dredge_bridge/bin/ and lib/dredge_bridge/obj/ are ordinary dotnet build
output, created the first time you open a DREDGE save. Safe to delete;
they'll be rebuilt automatically the next time cedit needs them.


LICENSE
-------
GPL-3.0 - see LICENSE.txt. lib/octopath_lib.py, lib/dredge_bridge/, and the
catalog files under data/octopath/ are adapted or vendored from your own
octopath-save-editor and dredge-se projects; everything else was written
new for cedit. LICENSE.txt has the full provenance breakdown.
