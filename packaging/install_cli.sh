#!/usr/bin/env bash
# Install cli.py on PATH as `cedit-cli`.
#
# Usage (from the repo root):
#     ./packaging/install_cli.sh              # installs to ~/.local/bin
#     ./packaging/install_cli.sh /usr/local/bin  # or install somewhere else
#
# cli.py has no PySide6/Qt dependency at all (only cedit.py itself and
# games/dredge_window.py need that - see README.txt's CLI section), so
# unlike install_app.sh this needs no venv, no build step, and works on
# macOS or Linux: just Python 3's standard library. This symlinks cli.py
# itself (rather than copying it or writing a wrapper script) so pulling
# later changes with `git pull` takes effect immediately, with nothing to
# reinstall.

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="${1:-$HOME/.local/bin}"
LINK_NAME="cedit-cli"

chmod +x "$REPO_ROOT/cli.py"
mkdir -p "$INSTALL_DIR"
ln -sf "$REPO_ROOT/cli.py" "$INSTALL_DIR/$LINK_NAME"

echo "Linked $INSTALL_DIR/$LINK_NAME -> $REPO_ROOT/cli.py"

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
