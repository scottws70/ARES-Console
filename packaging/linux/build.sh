#!/usr/bin/env bash
# Build Linux release artifacts into dist/:
#   ares-console_<ver>_all.deb          Debian/Ubuntu/Mint/Raspberry Pi OS package
#   ares-console-<ver>-linux.tar.gz     any distro: unpack and run ./install.sh (no root needed)
set -euo pipefail
umask 022
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VER="$(python3 -c "import sys; sys.path.insert(0, '$ROOT'); import ares_console; print(ares_console.__version__)")"
DIST="$ROOT/dist"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$DIST"

copy_app() {  # copy the python package (without caches) into $1
  mkdir -p "$1"
  (cd "$ROOT" && tar --exclude='__pycache__' --exclude='*.pyc' -cf - ares_console) | tar -xf - -C "$1"
}

# ---------------------------------------------------------------- .deb
PKG="$WORK/deb"
copy_app "$PKG/usr/lib/ares-console"
install -Dm755 /dev/stdin "$PKG/usr/bin/ares-console" <<'SH'
#!/bin/sh
PYTHONPATH=/usr/lib/ares-console exec python3 -m ares_console "$@"
SH
install -Dm644 "$ROOT/packaging/linux/ares-console.desktop" "$PKG/usr/share/applications/ares-console.desktop"
for s in 48 64 128 256; do
  install -Dm644 "$ROOT/packaging/icons/ares-console-$s.png" "$PKG/usr/share/icons/hicolor/${s}x${s}/apps/ares-console.png"
done
install -Dm644 "$ROOT/README.md" "$PKG/usr/share/doc/ares-console/README.md"
[ -f "$ROOT/LICENSE" ] && install -Dm644 "$ROOT/LICENSE" "$PKG/usr/share/doc/ares-console/copyright"
SIZE=$(du -sk "$PKG/usr" | cut -f1)
mkdir -p "$PKG/DEBIAN"
cat > "$PKG/DEBIAN/control" <<CTL
Package: ares-console
Version: $VER
Section: hamradio
Priority: optional
Architecture: all
Depends: python3 (>= 3.8)
Suggests: js8call, pat, libhamlib-utils
Installed-Size: $SIZE
Maintainer: ARES Console <https://github.com/scottws70/ARES-Console>
Homepage: https://github.com/scottws70/ARES-Console
Description: Net control console for ARES and emergency nets
 Check-in log with status/location/notes, live APRS-IS tracking map with
 offline tiles, ICS-213/214/205/309 and NTS radiogram forms, Winlink
 Standard Forms and SitRepNet MCForms, Winlink over ARDOP/Telnet with
 selective download, JS8Call integration, rig control via Hamlib rigctld,
 and a printable net summary report.
CTL
cat > "$PKG/DEBIAN/postinst" <<'SH'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
exit 0
SH
chmod 755 "$PKG/DEBIAN/postinst"
chmod -R u+rwX,go+rX,go-w "$PKG"
fakeroot dpkg-deb --build -Zxz "$PKG" "$DIST/ares-console_${VER}_all.deb" >/dev/null
echo "built $DIST/ares-console_${VER}_all.deb"

# ---------------------------------------------------------------- tar.gz
T="$WORK/ares-console-$VER"
copy_app "$T"
cp "$ROOT/README.md" "$ROOT/packaging/linux/install.sh" "$ROOT/packaging/linux/uninstall.sh" "$ROOT/packaging/linux/ares-console.desktop" "$T/"
[ -f "$ROOT/LICENSE" ] && cp "$ROOT/LICENSE" "$T/"
mkdir -p "$T/icons" && cp "$ROOT"/packaging/icons/ares-console-*.png "$T/icons/"
install -m755 /dev/stdin "$T/ares-console" <<'SH'
#!/bin/sh
# Run ARES Console straight from this folder (no install needed).
cd "$(dirname "$0")" && exec python3 -m ares_console "$@"
SH
chmod 755 "$T/install.sh" "$T/uninstall.sh"
tar -C "$WORK" -czf "$DIST/ares-console-$VER-linux.tar.gz" "ares-console-$VER"
echo "built $DIST/ares-console-$VER-linux.tar.gz"
