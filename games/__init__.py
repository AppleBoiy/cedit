"""
Game registry for cedit.

To add support for a new game:
  1. Create games/<yourgame>.py with a module-level 
     (see lib/base.py for the fields, games/duckov.py for a full example).
     Its own data/config normally goes in data/<yourgame>.json.
  2. Import it below and add it to _REGISTRY.

That's it - cedit.py itself never needs to change.
"""

from .bbee import PROFILE as BBEE_PROFILE
from .dave import PROFILE as DAVE_PROFILE
from .dredge import PROFILE as DREDGE_PROFILE
from .duckov import PROFILE as DUCKOV_PROFILE
from .hades import PROFILE as HADES_PROFILE
from .hades2 import PROFILE as HADES2_PROFILE
from .mhw import PROFILE as MHW_PROFILE
from .octopath import PROFILE as OCTOPATH_PROFILE

_REGISTRY = {
    DUCKOV_PROFILE.key: DUCKOV_PROFILE,
    OCTOPATH_PROFILE.key: OCTOPATH_PROFILE,
    DREDGE_PROFILE.key: DREDGE_PROFILE,
    DAVE_PROFILE.key: DAVE_PROFILE,
    BBEE_PROFILE.key: BBEE_PROFILE,
    MHW_PROFILE.key: MHW_PROFILE,
    HADES_PROFILE.key: HADES_PROFILE,
    HADES2_PROFILE.key: HADES2_PROFILE,
}


def list_games():
    """All registered GameProfiles, in registration order."""
    return list(_REGISTRY.values())


def get_game(key):
    return _REGISTRY[key]


def register_game(profile):
    """Add a GameProfile to the registry at import time."""
    _REGISTRY[profile.key] = profile
