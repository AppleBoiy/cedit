#!/usr/bin/env bash
# Build the standalone cedit-cli binary.
#
# Usage (from the repo root):
#     ./packaging/build_cli.sh
#
# Creates/reuses a venv at .venv-build (shared with build_app.sh) and
# installs PyInstaller into it, then builds dist/cedit-cli - a single
# self-contained executable, no Python install needed to run it, and
# (unlike build_app.sh) no PySide6 either: cli.py has no Qt dependency at
# all, see packaging/cedit_cli.spec's own comment for why. Works on
# whatever OS you run it on - Linux or macOS - since cli.py has no
# platform-specific code; the release workflow builds it on macOS
# alongside cedit.app, matching that release's platform.

set -euo pipefail
cd "$(dirname "$0")/.."

VENV_DIR=".venv-build"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating build venv at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r packaging/requirements.txt

# Only this build's own outputs - see build_app.sh's matching comment for
# why not the whole build/ and dist/ trees.
rm -rf build/cedit_cli dist/cedit-cli

pyinstaller packaging/cedit_cli.spec --noconfirm

echo
echo "Done. dist/cedit-cli is ready - see packaging/install_cli.sh to put it on PATH."
