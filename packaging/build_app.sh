#!/usr/bin/env bash
# Build cedit.app on macOS.
#
# Usage (from the repo root):
#     ./packaging/build_app.sh
#
# Creates/reuses a venv at .venv-build, installs the app's own runtime
# requirement (PySide6) plus PyInstaller, then builds dist/cedit.app.
# This must be run on macOS - PyInstaller produces a platform-specific
# bundle, and it can only be built on the OS you're targeting.

set -euo pipefail
cd "$(dirname "$0")/.."

VENV_DIR=".venv-build"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating build venv at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt
pip install -r packaging/requirements.txt

rm -rf build dist

pyinstaller packaging/cedit.spec --noconfirm

echo
echo "Done. dist/cedit.app is ready - double-click it, or drag it to /Applications."
