#!/usr/bin/env bash
# Install/start the LAMP top-bar indicator (GNOME/Ubuntu). Usage: topbar/install.sh [--remove]
# Writes ~/.config/autostart/lamp-indicator.desktop (start at login) and launches the indicator now.
set -euo pipefail
HERE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
DESKTOP="$HOME/.config/autostart/lamp-indicator.desktop"

if [ "${1:-}" = "--remove" ]; then
  rm -f "$DESKTOP"; pkill -f "$HERE/lamp_indicator.py" 2>/dev/null || true
  echo "removed autostart and stopped indicator"; exit 0
fi

python3 - <<'PY' || { echo "Not supported here. Needs GNOME + AppIndicator:
  sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1 gnome-shell-extension-appindicator libnotify-bin"; exit 1; }
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("AyatanaAppIndicator3", "0.1")
PY

mkdir -p "$(dirname "$DESKTOP")"
cat > "$DESKTOP" <<D
[Desktop Entry]
Type=Application
Name=LAMP projects
Comment=Top-bar control for lamp projects
Exec=python3 $HERE/lamp_indicator.py
Icon=network-server
X-GNOME-Autostart-enabled=true
D
pkill -f "$HERE/lamp_indicator.py" 2>/dev/null || true
nohup python3 "$HERE/lamp_indicator.py" >/dev/null 2>&1 &
echo "installed: autostart at login + running now. Remove: topbar/install.sh --remove"
