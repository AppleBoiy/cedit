#!/usr/bin/env bash
# Build (if needed) and install cedit-cli onto PATH.
#
# Usage (from the repo root):
#     ./packaging/install_cli.sh                 # build if missing, install to ~/.local/bin
#     ./packaging/install_cli.sh /usr/local/bin  # or install somewhere else
#     ./packaging/install_cli.sh --source        # skip building - symlink cli.py's source instead
#     ./packaging/install_cli.sh --source /usr/local/bin  # flags and a directory can combine
#
# Mirrors install_app.sh: builds dist/cedit-cli/ automatically (via
# ./packaging/build_cli.sh) if it doesn't exist yet. dist/cedit-cli/ is a
# folder (onedir build - see cedit_cli.spec's own comment for why: a
# onefile build re-unpacks its whole runtime on every launch, adding a
# very noticeable ~2s to something as trivial as `cedit-cli list-games`).
# This copies that whole folder into DATA_DIR below (a real copy, not a
# symlink - a binary can't "pick up" later source changes anyway, so
# rerun this script after any future build_cli.sh), then symlinks just
# the inner executable onto PATH, so `cedit-cli` still works as a normal
# single command regardless of the folder underneath it.
#
# --source skips all of that and symlinks cli.py's own source instead:
# no venv, no build step, works with just Python 3's standard library
# (cli.py has no PySide6/Qt dependency - see README.txt's CLI section),
# and a source symlink picks up later changes immediately on `git pull`.
# Use this if you don't want PyInstaller involved at all.

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LINK_NAME="cedit-cli"
DATA_DIR="$HOME/.local/share/cedit-cli"

SOURCE_MODE=0
INSTALL_DIR="$HOME/.local/bin"
for arg in "$@"; do
    if [ "$arg" = "--source" ]; then
        SOURCE_MODE=1
    else
        INSTALL_DIR="$arg"
    fi
done

mkdir -p "$INSTALL_DIR"

if [ "$SOURCE_MODE" = "1" ]; then
    chmod +x "$REPO_ROOT/cli.py"
    ln -sf "$REPO_ROOT/cli.py" "$INSTALL_DIR/$LINK_NAME"
    echo "Linked $INSTALL_DIR/$LINK_NAME -> $REPO_ROOT/cli.py (needs python3 on PATH)."
else
    if [ ! -d "$REPO_ROOT/dist/cedit-cli" ]; then
        echo "No dist/cedit-cli build found - building it first ..."
        "$REPO_ROOT/packaging/build_cli.sh"
    fi
    rm -rf "$DATA_DIR"
    mkdir -p "$(dirname "$DATA_DIR")"
    cp -R "$REPO_ROOT/dist/cedit-cli" "$DATA_DIR"
    ln -sf "$DATA_DIR/cedit-cli" "$INSTALL_DIR/$LINK_NAME"
    echo "Installed to $DATA_DIR, linked from $INSTALL_DIR/$LINK_NAME"
fi

case ":$PATH:" in
    *":$INSTALL_DIR:"*)
        echo
        echo "Try it: $LINK_NAME list-games"
        ;;
    *)
        echo
        echo "$INSTALL_DIR isn't on your PATH yet. Add this to your shell's rc file" \
             "(~/.zshrc, ~/.bashrc, ...) and open a new terminal:"
        echo
        echo "    export PATH=\"$INSTALL_DIR:\$PATH\""
        echo
        echo "Until then, run it directly: $INSTALL_DIR/$LINK_NAME list-games"
        ;;
esac
