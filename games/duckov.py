"""
cedit game profile: Escape from Duckov

Everything game-specific (save locations, the ES3 "missing value key" quirk,
the base64-packed item-variable fields, quick-edit fields) is declared in
data/duckov.json - there's nothing unusual enough about Duckov's save
format to need real Python here.
"""

import os

from lib.base import GameProfile

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "duckov.json")

PROFILE = GameProfile.from_config(_CONFIG_PATH)
