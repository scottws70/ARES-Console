#!/bin/sh
# Install ARES Console for the current user (no root needed).
#   App:      ~/.local/share/ares-console-app
#   Command:  ~/.local/bin/ares-console
#   Menu:     Applications > Ham Radio > ARES Console
# Your data (~/.local/share/ares-console) is never touched by install or uninstall.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
command -v python3 >/dev/null 2>&1 || { echo "Python 3 is required: install it with your package manager (e.g. sudo apt install python3)"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' || { echo "Python 3.8 or newer is required"; exit 1; }
APP="$HOME/.local/share/ares-console-app"
BIN="$HOME/.local/bin"
rm -rf "$APP"
mkdir -p "$APP" "$BIN" "$HOME/.local/share/applications"
cp -r "$SRC/ares_console" "$APP/"
cat > "$BIN/ares-console" <<SH
#!/bin/sh
PYTHONPATH="$APP" exec python3 -m ares_console "\$@"
SH
chmod 755 "$BIN/ares-console"
for s in 48 64 128 256; do
  mkdir -p "$HOME/.local/share/icons/hicolor/${s}x${s}/apps"
  cp "$SRC/icons/ares-console-$s.png" "$HOME/.local/share/icons/hicolor/${s}x${s}/apps/ares-console.png"
done
sed "s|^Exec=.*|Exec=$BIN/ares-console|" "$SRC/ares-console.desktop" > "$HOME/.local/share/applications/ares-console.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$HOME/.local/share/applications" || true
echo "ARES Console installed."
echo "Start it from your applications menu (ARES Console), or run: $BIN/ares-console"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "(Add $BIN to your PATH to run 'ares-console' from a terminal.)";; esac
