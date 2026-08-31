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
  - Monster Hunter World: Iceborne (games/mhw.py + games/mhw_window.py +
      lib/mhw_crypto.py + data/mhw/ - dedicated editor window like DREDGE's;
      item pouch/storage is a searchable, item-centric grid (every item
      that belongs in a container, real name, quantity editable in place -
      2774 items catalogued) and equipment resolves to real names too
      (11421 armor/charms/weapons/kinsects))
  - Hades                    (games/hades.py + lib/hades_lib.py + data/hades.json)
  - Hades II                 (games/hades2.py + games/hades_window.py + lib/hades_lib.py +
      data/hades2.json + data/hades2/ - Supergiant SGB1 binary container with
      Adler32 checksums, LZ4 block compression, and embedded Luabins state.
      Full tree/table view, DictTableDialog spreadsheet, Quick Edit shortcuts,
      item spawner, and a dedicated 9-tab Editor Suite with fine-tuning step
      buttons and tester presets)

VERSION at the repo root is the single source of truth for cedit's own
version - shown in the GUI's status bar footer and `cedit.py --version`,
`cedit-cli --version`, and both PyInstaller specs' bundled version. Bump
that one file (`make release VERSION=x.y.z` does this, plus tagging) and
everything else follows from it.


RUNNING IT
----------
    pip install -r requirements.txt   # installs PySide6 + pycryptodome
    python3 cedit.py
    python3 cedit.py --game duckov /path/to/Save_1.sav

Requires Python 3, PySide6 (`pip install PySide6`), and pycryptodome
(only actually used by games/mhw.py's AES/Blowfish - see lib/mhw_crypto.py).
No separate system package needed for PySide6 - it bundles its own Qt
build, unlike Tkinter which depends on whatever Tcl/Tk your Python
happens to be linked against.


CLI (scripting without the GUI)
--------------------------------
cli.py gives scriptable, headless access to the same GameProfile logic
the GUI uses - reading/editing arbitrary fields, spawning/removing items,
browsing an inventory or item catalog - without opening any window.
Doesn't need PySide6 installed at all (see FOLDER LAYOUT below for why):

    python3 cli.py list-games
    python3 cli.py get --game duckov --save Save_1.sav --path EconomyData.value.money
    python3 cli.py set --game duckov --save Save_1.sav --path EconomyData.value.money --value 999999
    python3 cli.py targets --game duckov --save Save_1.sav
    python3 cli.py inventory --game duckov --save Save_1.sav --target backpack
    python3 cli.py spawn --game duckov --save Save_1.sav --target backpack --item 594 --quantity 3
    python3 cli.py remove --game duckov --save Save_1.sav --target backpack --instance -116
    python3 cli.py catalog --game duckov --search rifle

Or install it once as a `cedit-cli` command on your PATH:
`./packaging/install_cli.sh` (installs to ~/.local/bin by default; pass a
different directory as an argument, e.g. `./packaging/install_cli.sh
/usr/local/bin`). Builds dist/cedit-cli automatically if it doesn't
already exist (same as install_app.sh does for cedit.app), then installs
that standalone build - no Python install needed at all to run it. It's
a onedir build, not onefile (deliberately - see packaging/cedit_cli.spec's
comment: onefile re-unpacks its whole bundled runtime on every launch,
which turns something as trivial as `cedit-cli list-games` into a very
noticeable ~2 second wait; onedir's files just sit on disk, so each
launch is near-instant instead), so this copies the whole build to
~/.local/share/cedit-cli and symlinks just its executable onto PATH -
`cedit-cli` still works as a normal single command either way. Pass
--source to skip building entirely and symlink cli.py's own source
instead (needs python3 on PATH, but nothing to reinstall after a
`git pull`, since cli.py has no PySide6 dependency at all - see FOLDER
LAYOUT below).

Every write goes through the same backup-then-atomic-replace path as the
GUI (pass --no-backup to skip the .bak). DREDGE can't be used this way -
it has no loads/dumps at all (see games/dredge.py) - every command tells
you so cleanly rather than pretending to support it. Run `python3 cli.py
<command> --help` for each command's full option list, or see cli.py's
own module docstring.


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

Or skip the manual drag: `./packaging/install_app.sh` builds (if
dist/cedit.app doesn't exist yet - pass --rebuild to force a fresh build)
and copies it straight into /Applications/cedit.app, clearing the
quarantine flag itself (safe to do automatically here, since it's your
own local build, not a download).

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


RELEASING (automated cedit.app + cedit-cli builds)
----------------------------------------------------
Push a version tag and GitHub Actions builds both cedit.app and the
standalone cedit-cli binary on macOS and attaches them to a new GitHub
Release automatically - no local build needed to hand someone a copy:

    git tag v1.0.0
    git push origin v1.0.0

That triggers .github/workflows/release.yml, which runs the test suite,
builds packaging/cedit.spec and packaging/cedit_cli.spec on a
macos-latest runner, zips each, and publishes them as release assets
(cedit-macos.zip, cedit-cli-macos.zip) with auto-generated release notes.
Bump the tag (v1.0.1, v1.1.0, ...) for each new release. Someone who only
grabs cedit-cli-macos.zip from a Release (never clones the repo at all)
still gets a fully working cedit-cli - unzip it, then either run
cedit-cli/cedit-cli directly or point install_cli.sh-style PATH setup at
it (it's a folder, same onedir shape as install_cli.sh installs locally -
see that section above). See packaging/cedit_cli.spec's own comment for
how it stays free of cedit.app's PySide6/Qt weight.

The built app is unsigned and not notarized (that needs a paid Apple
Developer account), so macOS Gatekeeper will warn on first launch -
right-click cedit.app > Open once to get past it, or:
    xattr -dr com.apple.quarantine cedit.app


FOLDER LAYOUT
-------------
    cedit.py    - the generic editor: menus, tree view, quick-edit panel,
                  raw JSON preview, file I/O. Has no per-game logic at all.
    cli.py      - scriptable, headless equivalent of the GUI's editing
                  actions (get/set/spawn/remove/inventory/catalog) - see
                  the CLI section above.
    games/      - one module per game, each exporting a `PROFILE` object
                  (see lib/base.py's GameProfile for the contract). Every
                  games/*.py is plain Python with no PySide6 dependency
                  except games/dredge_window.py (DREDGE's actual window -
                  games/dredge.py itself only imports that module lazily,
                  inside custom_launcher, so `import games` never requires
                  PySide6 - that's what lets cli.py work without it too).
    lib/        - lib/base.py (the shared plugin contract + utilities) plus
                  any game's own parsing code too unusual to be pure config
                  (lib/octopath_lib.py, lib/dredge_client.py).
    data/       - per-game config/data files a games/<name>.py loads at
                  import time (data/duckov.json, data/octopath/*.json,
                  data/dredge/*.json).
    packaging/  - PyInstaller specs, build/install scripts, and app icon
                  for both cedit.app (cedit.spec, build_app.sh,
                  install_app.sh - see PACKAGING above) and the
                  standalone cedit-cli binary (cedit_cli.spec,
                  build_cli.sh, install_cli.sh - see the CLI section
                  above).


PER-GAME NOTES
---------------

Escape from Duckov
  Plain-JSON Unity Easy Save 3 format, fully editable through the generic
  tree editor - including inventory (Item/MainCharacterItemData for the
  backpack/equipped items, Inventory/PlayerStorage and
  Inventory/Inventory_Safe for base storage). Edit > Inventory Editor...
  opens a dedicated full window (like DREDGE's own inventory window) for
  the backpack, player storage, and the safe: a visual grid colored by
  occupied/free slot, a side list of what's in each slot (position, type
  id, instance id), and Spawn/Remove buttons. Spawning adds a brand-new
  item by numeric type id - it handles this format's own item-tree
  linking (unique instanceIDs, equipment slotContents, inventory position
  lists, capacity limits on storage containers) so you don't have to
  construct that structure by hand through the generic tree. There's no
  publicly published item name catalog for this game, but data/duckov/
  item_names.json has a real one anyway - extracted directly from a local
  install's own game files (see data/duckov/README.md), covering 1568
  items. Both the generic tree and the Inventory Editor window show a
  looked-up name next to a typeID wherever this catalog covers it; ids it
  doesn't cover just show as a bare number. The Inventory Editor's
  "Browse Catalog..." button opens a searchable name/id picker over the
  whole catalog, so spawning an item doesn't require already knowing its
  numeric id. Each unit of a spawned
  quantity is its own separate item entry rather than one entry with a
  fabricated "Count" - whether an item type is actually stackable, and
  under which field, is something only the game's own catalog would know
  for certain.
  Removing an item also removes anything nested inside it (e.g. a stored
  container's contents); only the top-level slots this window shows are
  removable this way - a stored item that's itself a container needs the
  generic tree editor for its own nested contents. Backpack capacity
  isn't recorded anywhere in the save (it depends on whichever backpack
  item is equipped), so that grid only shows what's occupied plus a
  handful of empty slots to spawn into, rather than a real total.

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



Hades / Hades II
  Supergiant SGB1 binary container format (Profile1.sav .. Profile4.sav and
  Profile1_Temp.sav), decoded and encoded by lib/hades_lib.py with Adler-32
  checksum verification and LZ4 block compression/decompression for the
  embedded Luabins game state. Once decompressed, the entire GameState
  hierarchy (Resources, Arcana MetaUpgradeState, KeepsakeChambers,
  WeaponsUnlocked, WorldUpgradesAdded, CaughtFish, and CurrentRun Hero stats)
  is exposed directly in cedit's generic tree and JSON editor, while
  common currencies (Bones, Ash, Psyche, Fate Fabric, Silver, Darkness, Keys,
  Gems, Titan Blood) and run counts are wired to the Quick Edit bar.
  Right-clicking any dictionary node (such as Resources or MetaUpgradeState)
  and choosing 'View as Table...' opens a spreadsheet dialog (DictTableDialog)
  with live search filtering and in-place cell editing.
  For a specialized view matching in-game progression, the toolbar's 'Hades
  Suite...' button (or Edit > Hades Editor Suite...) opens a dedicated 9-tab
  editor window (games/hades_window.py): General (God Mode level, Hell Mode,
  Runs, Grasp, Location), Resources (all 29 common currencies, ores, boss
  drops, and alchemy reagents), Garden (27 harvested flora, grown crops, and
  seeds), Gifts & Indulgences (13 affinity items, Obol points, bath salts),
  Fish Catches (27 regional catches), Arcana Cards (all 25 cards with Rank 1-3
  and Unlocked status), Keepsakes (all 33 keepsakes with chamber affinity
  progress), Unlocks & Aspects (all 6 hidden weapon aspects, Crossroads
  upgrades, and boss difficulty modifiers), and Active Run (live health,
  magick, death defiances, and rerolls). Every resource row includes fine-tuning
  step buttons (-100, -10, -1, +1, +10, +100) alongside batch tester presets
  (+10 All Materials, +1,000 All Currencies, Max Arcana, Unlock Hidden Aspects).
  Save discovery strictly targets valid Profile*.sav files, filtering out
  verification cache files (Profile1.v.sav), .bak backups, .sjson configs,
  and .ctrls files automatically.
  Additionally, File > Fix Texture (Hades II)... (also accessible via the
  Fix Textures... button in the Hades Editor Suite) provides an integrated
  resolution fix for devices with integrated graphics or lower VRAM (including
  Apple Silicon and handheld PCs), where Hades II automatically downscales to
  720p assets even on High settings. The fix swaps the 720p and 1080p asset
  directories in Content/Movies and Content/Packages to force full 1080p high-
  resolution graphics.


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
