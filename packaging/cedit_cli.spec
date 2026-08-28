# PyInstaller spec for the standalone cedit-cli binary.
#
# Build (from the repo root, with packaging/requirements.txt installed
# into your venv):
#     pyinstaller packaging/cedit_cli.spec --noconfirm
#
# Output lands in dist/cedit-cli/ - a folder (onedir, not onefile) whose
# dist/cedit-cli/cedit-cli is the actual executable. Deliberately onedir,
# matching how cedit.spec builds cedit.app: a onefile build re-extracts
# its entire bundled runtime into a temp dir on every single launch and
# deletes it on exit, which is where a "trivial" `cedit-cli list-games`
# picks up a very noticeable ~2s of pure unpack/cleanup overhead on top
# of actually running. Onedir already has its files sitting on disk, so
# each launch skips all of that - see packaging/install_cli.sh for how
# this folder gets installed (it symlinks the inner executable onto
# PATH, not the folder itself). See packaging/build_cli.sh for a
# one-line wrapper.
#
# Unlike cedit.spec, this one needs no PySide6 at all: cli.py's own
# _require_scriptable() guard means it never actually calls
# games/dredge.py's launch() (the only place that imports PySide6, and
# only lazily - see that module's docstring), but PyInstaller's static
# import scan doesn't know that - it'd otherwise still find and follow
# that import edge purely from the bytecode, pulling in all of PySide6/Qt
# for a "lightweight" CLI binary. excludes below heads that off, so this
# builds (and stays small) whether or not PySide6 is even installed.

import os

block_cipher = None

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(SPEC)), ".."))


def collect_dir(rel_path):
    """Recursively collect every file under REPO_ROOT/rel_path as an
    explicit (source_file, dest_dir) pair - see cedit.spec's identical
    helper for why (not duplicated as a shared import: PyInstaller execs
    spec files standalone, not as part of the normal package)."""
    pairs = []
    src_dir = os.path.join(REPO_ROOT, rel_path)
    if not os.path.isdir(src_dir):
        return pairs
    for root, dirs, files in os.walk(src_dir):
        for name in files:
            full = os.path.join(root, name)
            rel_dir = os.path.relpath(root, REPO_ROOT)
            pairs.append((full, rel_dir))
    return pairs


datas = collect_dir("data")

a = Analysis(
    [os.path.join(REPO_ROOT, "cli.py")],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # DREDGE has no CLI support anyway (see cli.py's _require_scriptable) -
    # this just stops PyInstaller's analysis from following that dead-end
    # import edge into PySide6/shiboken6 at all.
    excludes=["games.dredge_window", "PySide6", "shiboken6"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="cedit-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="cedit-cli",
)
