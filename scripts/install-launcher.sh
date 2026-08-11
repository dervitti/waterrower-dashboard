#!/usr/bin/env bash
# Launcher für dmenu / Anwendungsmenü installieren.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
NAME="waterrower"
DESKTOP_NAME="waterrower-dashboard.desktop"

mkdir -p "$BIN_DIR" "$APP_DIR"

# PATH-Eintrag für dmenu_run / wofi / fuzzel
WRAPPER="$BIN_DIR/$NAME"
cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
# WaterRower Dashboard — von dmenu aufrufbar
cd "$ROOT" || exit 1
exec ./start.sh
EOF
chmod +x "$WRAPPER"
chmod +x "$ROOT/start.sh"

# Terminal für Desktop-Eintrag finden
pick_term() {
  if [[ -n "${TERMINAL:-}" ]] && command -v "$TERMINAL" >/dev/null 2>&1; then
    echo "$TERMINAL"
    return
  fi
  for t in foot kitty alacritty wezterm ghostty gnome-terminal konsole xfce4-terminal xterm; do
    if command -v "$t" >/dev/null 2>&1; then
      echo "$t"
      return
    fi
  done
  echo ""
}

TERM_BIN="$(pick_term)"
DESKTOP="$APP_DIR/$DESKTOP_NAME"

if [[ -n "$TERM_BIN" ]]; then
  case "$TERM_BIN" in
    gnome-terminal)
      EXEC="$TERM_BIN -- bash -lc 'cd \"$ROOT\" && exec ./start.sh'"
      ;;
    konsole)
      EXEC="$TERM_BIN -e bash -lc 'cd \"$ROOT\" && exec ./start.sh'"
      ;;
    *)
      # foot, kitty, alacritty, xterm, …
      EXEC="$TERM_BIN -e bash -lc 'cd \"$ROOT\" && exec ./start.sh'"
      ;;
  esac
  TERMINAL_KEY=false
else
  EXEC="bash -lc 'cd \"$ROOT\" && exec ./start.sh'"
  TERMINAL_KEY=true
fi

cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=WaterRower Dashboard
Comment=S4 Live-Dashboard (venv + Server + Browser)
Keywords=rower;waterrower;training;usb;s4;
Icon=utilities-system-monitor
Categories=Sports;Utility;
Terminal=$TERMINAL_KEY
Exec=$EXEC
Path=$ROOT
StartupNotify=false
EOF

# Desktop-Datenbank aktualisieren (falls vorhanden)
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR" 2>/dev/null || true
fi

echo "Installiert:"
echo "  dmenu_run / PATH:  $WRAPPER"
echo "  Desktop-Eintrag:   $DESKTOP"
if [[ -n "$TERM_BIN" ]]; then
  echo "  Terminal:          $TERM_BIN"
else
  echo "  Terminal:          (Desktop Terminal=true — setze \$TERMINAL falls nötig)"
fi
echo
echo "In dmenu nach „waterrower“ oder „WaterRower“ suchen."
echo "Falls dmenu den Befehl nicht sieht: shell neu starten oder"
echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
echo "in ~/.bashrc / ~/.zshrc / sway config prüfen."
