"""
cedit game profile: Escape from Duckov

Everything game-specific (save locations, the ES3 "missing value key" quirk,
the base64-packed item-variable fields, quick-edit fields) is declared in
data/duckov.json - there's nothing unusual enough about Duckov's save
format to need real Python here.
"""

from pathlib import Path

from lib.base import GameProfile

# Path(__file__).resolve() (not os.path.dirname(__file__) + "..") because
# under a PyInstaller bundle, games/*.py is embedded straight into the
# frozen archive - __file__ points at a synthetic "games/duckov.py" path
# whose "games" directory never actually exists on disk. A literal
# ".."-containing path like ".../games/../data/x.json" then fails to open
# (the OS has to actually enter "games" before it can apply ".."), even
# though "data" itself is a real, present directory. Path.resolve() (non-
# strict by default) collapses ".." lexically instead, so it works whether
# or not the intermediate directory is real.
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "duckov.json"

PROFILE = GameProfile.from_config(_CONFIG_PATH)
