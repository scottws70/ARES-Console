#!/bin/sh
# Remove ARES Console installed by install.sh. Your logs and settings in
# ~/.local/share/ares-console are kept; delete that folder yourself if you want them gone.
rm -rf "$HOME/.local/share/ares-console-app" "$HOME/.local/bin/ares-console" \
       "$HOME/.local/share/applications/ares-console.desktop"
for s in 48 64 128 256; do rm -f "$HOME/.local/share/icons/hicolor/${s}x${s}/apps/ares-console.png"; done
echo "ARES Console removed. Your data is still in ~/.local/share/ares-console"
