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
  - Dave the Diver           (games/dave.py + data/dave/)
  - BlazBlue Entropy Effect  (games/bbee.py + lib/bbee_lib.py)


RUNNING IT
----------
    pip install -r requirements.txt   # installs PySide6
    python3 cedit.py
    python3 cedit.py --game duckov /path/to/Save_1.sav

Requires Python 3 and PySide6 (`pip install PySide6`). No separate system
package needed - PySide6 bundles its own Qt build, unlike Tkinter which
depends on whatever Tcl/Tk your Python happens to be linked against.


SEARCH
------
Type a query into the toolbar's Find box and press Enter (or click
Search) to open a Search Results panel listing every match in the file at
once - key and value for each, not just the first one. Double-click a row
(or select it and click "Jump to Selected") to reveal and select that
node in the tree. The panel stays open across searches, so you can jump
to one result, look at it, then come back and try another. Search always
looks at the underlying save data directly, not just whichever tree
branches happen to be expanded, so it never misses a match hidden under a
collapsed node.


RECENT FILES
------------
File > Open Recent lists the last 10 files you've opened (across all
games), newest first, each labeled with which game it belongs to.
Choosing one switches to that game first if needed, then opens it -
same confirm-before-discarding-changes prompt as switching games
manually. Persisted via Qt's native per-OS settings storage, so it
survives restarts without cedit managing its own config file. DREDGE
saves never appear here (its window doesn't go through this path).


UNDO / REDO
-----------
Edit > Undo (Ctrl+Z) and Redo cover every mutating action in the generic
editor - quick-edit apply, tree double-click edits, Add Key/Delete
Selected, Apply Raw -> Tree, and edits made through a list's "View as
Table" dialog. Each is a full snapshot of the save data from just before
that action, so Undo always cleanly reverts one whole action at a time.
History is cleared on Open/Reload/switching games (there's nothing
meaningful to undo back into a different file). DREDGE's own window
doesn't use this - it has its own pending-changes-until-Apply model
instead.


PACKAGING (build a real cedit.app)
-----------------------------------
So you don't have to keep lining up the right Python/pip every time (this
is what bit you once already, with a conda/Homebrew mismatch), you can
build cedit into a real double-clickable cedit.app with PySide6 baked in:

    ./packaging/build_app.sh

This creates a throwaway build venv (.venv-build), installs PySide6 +
PyInstaller into it, and produces dist/cedit.app. Drag that into
/Applications and launch it like any other Mac app - no terminal, no
Python environment to get right, ever again.

Must be run on macOS (PyInstaller bundles are platform-specific, and this
one was only ever built/tested there - it can't be built or verified from
a Linux CI runner). Rebuild it any time you pull new changes.

What's bundled: cedit.py, everything under games/ and lib/, the data/
folder (item/monster catalogs, DREDGE manifest if you've generated one),
and lib/dredge_bridge/'s C# *source* (not its bin/obj build output - the
bridge still builds itself with your local .NET SDK the first time you
open a DREDGE save inside the bundled app, exactly like running from
source). packaging/cedit.spec is the PyInstaller spec if you want to
tweak what's included; packaging/cedit.icns is the app icon.

Not handled by packaging: DREDGE saves still need a local DREDGE install
(for its Assembly-CSharp.dll) and a .NET SDK on the machine running the
bundle - those aren't things a Python bundle can carry for you.


RELEASING (automated cedit.app builds)
----------------------------------------
Push a version tag and GitHub Actions builds cedit.app on macOS and
attaches it to a new GitHub Release automatically - no local build needed
to hand someone a copy:

    git tag v1.0.0
    git push origin v1.0.0

That triggers .github/workflows/release.yml, which runs the test suite,
builds packaging/cedit.spec on a macos-latest runner, zips dist/cedit.app,
and publishes it as a release asset (cedit-macos.zip) with auto-generated
release notes. Bump the tag (v1.0.1, v1.1.0, ...) for each new release.

The built app is unsigned and not notarized (that needs a paid Apple
Developer account), so macOS Gatekeeper will warn on first launch -
right-click cedit.app > Open once to get past it, or:
    xattr -dr com.apple.quarantine cedit.app


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
    packaging/  - PyInstaller spec, build script, and app icon for
                  building a real cedit.app - see PACKAGING above.


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

Dave the Diver (Steam / macOS)
  *_GD.sav files are JSON obfuscated with a repeating XOR cipher keyed on
  the ASCII string "GameData" (applied per UTF-16 code unit, not per byte
  - the same scheme the game itself uses), decoded/encoded automatically
  by games/dave.py. Once decoded it's plain JSON, so - like Duckov -
  everything in it is freely editable through the generic tree editor;
  Gold/Bei/Artisan's Flame/research-trust-fake points/Jungle DLC currency
  are wired up as Quick Edit fields. Materials (Ingredients) and Items
  (InventoryItemSlot) are dicts keyed by ingredient id / item GUID rather
  than lists, so they show as an expandable tree node instead of a table
  - edit an entry's count directly, or use Add Key to Selected for a new
  item id. Each entry's row shows a looked-up item name next to it via
  data/dave/item_names.json (coverage is complete for materials, partial
  for general items - see data/dave/README.md); an id with no match just
  shows with no name, cross-reference a wiki/datamine for those.
  Saving is blocked outright while the game process appears to be
  running or the file is held open elsewhere (its next autosave would
  silently overwrite your edit otherwise) - quit the game fully first,
  and give Steam Cloud sync a moment before relaunching. Ported from your
  own standalone AppleBoiy/dave-editor project.

BlazBlue Entropy Effect (Steam)
  A save slot (named just a digit, "1".."9", no extension) is an
  LZ4-framed schema-less protobuf message. Deliberately narrow scope,
  matching the source project's own README exactly: only persistent
  Analysis Points (AP) is ever read or written (wired up as a Quick Edit
  field); everything else in the save has no field names in this format
  (a schema-less protobuf message only has numbered fields), so it isn't
  parsed or exposed at all - not even read-only. Needs the `lz4`
  command-line tool on PATH (`brew install lz4` on macOS) - set BBEE_LZ4
  if it's installed somewhere unusual. Every save re-decompresses the
  original file fresh, edits only the nested containers on the path to
  AP (everything else keeps its original bytes and order), then
  re-decompresses and re-parses the freshly-written bytes to confirm AP
  actually reads back correctly before cedit ever touches the real file.
  Ported from your own standalone AppleBoiy/bbee-se project.

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
