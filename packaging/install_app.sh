#!/usr/bin/env bash
# Build (if needed) and install cedit.app into /Applications on macOS.
#
# Usage (from the repo root):
#     ./packaging/install_app.sh          # build if dist/cedit.app is missing/stale, then install
#     ./packaging/install_app.sh --rebuild  # always rebuild first, even if dist/cedit.app exists
#
# This only installs a local copy for the account running it - it does not
# code-sign or notarize anything (that needs a paid Apple Developer
# account), so it clears the quarantine flag itself rather than making you
# right-click > Open once, since you just built this copy yourself on this
# machine.

set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$(uname)" != "Darwin" ]; then
    echo "install_app.sh only works on macOS (cedit.app is a macOS-specific PyInstaller bundle)." >&2
    exit 1
fi

REBUILD=0
if [ "${1:-}" = "--rebuild" ]; then
    REBUILD=1
fi

if [ "$REBUILD" = "1" ] || [ ! -d "dist/cedit.app" ]; then
    echo "Building dist/cedit.app ..."
    ./packaging/build_app.sh
else
    echo "Using existing dist/cedit.app (pass --rebuild to force a fresh build)."
fi

if [ ! -d "dist/cedit.app" ]; then
    echo "dist/cedit.app still doesn't exist after building - see the output above for what went wrong." >&2
    exit 1
fi

DEST="/Applications/cedit.app"

if [ -d "$DEST" ]; then
    echo "Removing the existing $DEST ..."
    rm -rf "$DEST"
fi

echo "Copying dist/cedit.app to $DEST ..."
ditto "dist/cedit.app" "$DEST"

echo "Clearing the quarantine flag (this is your own local build, not a download) ..."
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

echo
echo "Installed. Open it from /Applications, Spotlight, or Launchpad like any other app."
