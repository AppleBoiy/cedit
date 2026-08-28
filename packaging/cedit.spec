# PyInstaller spec for cedit.app
#
# Build (from the repo root, on macOS, with packaging/requirements.txt
# installed into your venv):
#     pyinstaller packaging/cedit.spec --noconfirm
#
# Output lands in dist/cedit.app - see packaging/build_app.sh for a
# one-line wrapper that also creates a venv and installs everything.

import os

block_cipher = None

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(SPEC)), ".."))


def collect_dir(rel_path):
    """Recursively collect every file under REPO_ROOT/rel_path as an
    explicit (source_file, dest_dir) pair. More reliable across
    PyInstaller versions than passing a bare directory as a datas source
    (some versions silently drop directory-form datas entries)."""
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


def collect_dredge_bridge_sources():
    """lib/dredge_bridge/ contains vendored C# source (.cs/.csproj) that the
    app builds itself on first use of a DREDGE save - bundle the source,
    not bin/ or obj/ (those are gitignored build output regenerated
    per-machine by `dotnet build`)."""
    pairs = []
    src_dir = os.path.join(REPO_ROOT, "lib", "dredge_bridge")
    if not os.path.isdir(src_dir):
        return pairs
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d not in ("bin", "obj")]
        for name in files:
            full = os.path.join(root, name)
            rel_dir = os.path.relpath(root, REPO_ROOT)
            pairs.append((full, rel_dir))
    return pairs


with open(os.path.join(REPO_ROOT, "VERSION"), encoding="utf-8") as _f:
    APP_VERSION = _f.read().strip()

datas = [
    (os.path.join(REPO_ROOT, "packaging", "icon.png"), "packaging"),
    # At the bundle root (not a subfolder) so _resource_path("VERSION")
    # in cedit.py (which joins straight onto sys._MEIPASS) finds it.
    (os.path.join(REPO_ROOT, "VERSION"), "."),
]
datas += collect_dir("data")
datas += collect_dredge_bridge_sources()

a = Analysis(
    [os.path.join(REPO_ROOT, "cedit.py")],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=datas,
    # games/dredge.py imports games.dredge_window lazily (inside a function,
    # not at module level - see its own docstring for why), so PyInstaller's
    # static import scan can miss it; spell it out explicitly here.
    hiddenimports=["games.dredge_window"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name="cedit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
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
    name="cedit",
)

app = BUNDLE(
    coll,
    name="cedit.app",
    icon=os.path.join(REPO_ROOT, "packaging", "cedit.icns"),
    bundle_identifier="dev.chaipat.cedit",
    info_plist={
        "CFBundleName": "cedit",
        "CFBundleDisplayName": "cedit",
        "CFBundleShortVersionString": APP_VERSION,
        "NSHighResolutionCapable": True,
    },
)
