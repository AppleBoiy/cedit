#!/usr/bin/env bash
# Install cedit-cli on PATH.
#
# Usage (from the repo root):
#     ./packaging/install_cli.sh              # installs to ~/.local/bin
#     ./packaging/install_cli.sh /usr/local/bin  # or install somewhere else
#
# Prefers a prebuilt dist/cedit-cli binary (from ./packaging/build_cli.sh,
# or downloaded from a GitHub Release) if one exists - a real copy, since
# a binary can't "pick up" later source changes the way a symlink would
# anyway. Otherwise falls back to symlinking cli.py's own source: it has
# no PySide6/Qt dependency at all (only cedit.py itself and
# games/dredge_window.py need that - see README.txt's CLI section), so
# that fallback needs no venv, no build step, and works on macOS or
# Linux with just Python 3's standard library - and unlike the binary
# path, a source symlink picks up later changes immediately on
# `git pull`, with nothing to reinstall.

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="${1:-$HOME/.local/bin}"
LINK_NAME="cedit-cli"

mkdir -p "$INSTALL_DIR"

if [ -x "$REPO_ROOT/dist/cedit-cli" ]; then
    cp "$REPO_ROOT/dist/cedit-cli" "$INSTALL_DIR/$LINK_NAME"
    chmod +x "$INSTALL_DIR/$LINK_NAME"
    echo "Copied dist/cedit-cli -> $INSTALL_DIR/$LINK_NAME"
    echo "(This is a snapshot, not a symlink - rerun this script after any future ./packaging/build_cli.sh.)"
else
    chmod +x "$REPO_ROOT/cli.py"
    ln -sf "$REPO_ROOT/cli.py" "$INSTALL_DIR/$LINK_NAME"
    echo "No dist/cedit-cli binary found (run ./packaging/build_cli.sh first for a standalone one)."
    echo "Linked $INSTALL_DIR/$LINK_NAME -> $REPO_ROOT/cli.py instead (needs python3 on PATH)."
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
