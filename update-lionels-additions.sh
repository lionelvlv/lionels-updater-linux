#!/usr/bin/env bash
# Lionel's Additions updater for Linux. Keep this file: run it again whenever there is an update.
#   ./update-lionels-additions.sh               update (or install) the pack
#   ./update-lionels-additions.sh the.zip       use an update zip you downloaded yourself
# It fetches the newest updater logic (update_linux.py) from GitHub and runs it with python3; offline, it runs the copy
# beside this file if there is one.
# lionels-updater linux stub

# Its own repo since 2026-10-21 (lionelvlv/lionels-updater-linux); the main repo keeps a copy for older .sh files.
logic_url="${LIONEL_UPDATER_LOGIC_URL:-https://raw.githubusercontent.com/lionelvlv/lionels-updater-linux/main}/update_linux.py"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
self="$here/$(basename "${BASH_SOURCE[0]}")"

# Started from a file manager without a terminal: open one, so the questions can be answered.
if [ ! -t 0 ] && [ -z "$LIONEL_UPDATER_IN_TERMINAL" ] && [ -n "$DISPLAY$WAYLAND_DISPLAY" ]; then
  export LIONEL_UPDATER_IN_TERMINAL=1
  for t in x-terminal-emulator gnome-terminal konsole xfce4-terminal kitty alacritty xterm; do
    command -v "$t" >/dev/null 2>&1 || continue
    case "$t" in
      gnome-terminal) exec "$t" -- bash "$self" "$@" ;;
      *) exec "$t" -e bash "$self" "$@" ;;
    esac
  done
fi

pause() { if [ -t 0 ] && [ -z "$LIONEL_UPDATER_NO_PAUSE" ]; then echo; read -r -p "Press Enter to close. " _; fi; }

py="$(command -v python3)"
if [ -z "$py" ]; then
  echo "This updater needs Python 3. Install it with your package manager, for example:"
  echo "  sudo apt install python3      (Ubuntu, Debian, Mint)"
  echo "  sudo dnf install python3      (Fedora)"
  echo "  sudo pacman -S python         (Arch)"
  pause; exit 1
fi

tmp="$(mktemp -d "${TMPDIR:-/tmp}/lionels-updater-logic.XXXXXX")" || { echo "Could not make a temporary folder."; pause; exit 1; }
trap 'rm -rf "$tmp"' EXIT
script=""
# Prints why it failed (no connection, or GitHub answering 404 because the file is not published there yet).
why="$("$py" -I -c 'import sys, urllib.request
try:
    r = urllib.request.urlopen(urllib.request.Request(sys.argv[1], headers={"User-Agent": "lionels-updater-linux"}), timeout=30)
    open(sys.argv[2], "wb").write(r.read())
except Exception as e:
    print(e); sys.exit(1)' "$logic_url" "$tmp/update_linux.py" 2>&1)"
if [ -z "$why" ] && grep -q "^# Lionel's Additions updater for Linux: the logic." "$tmp/update_linux.py"; then
  script="$tmp/update_linux.py"
elif [ -f "$here/update_linux.py" ]; then
  echo "(Could not get the newest updater from GitHub: using the copy beside this file.)"
  script="$here/update_linux.py"
else
  echo "The updater could not be downloaded from GitHub: ${why:-not the updater file}"
  echo "  $logic_url"
  case "$why" in
    *404*) echo "It is not on GitHub yet. Ask Lionel, or put update_linux.py from him in the same folder as this file." ;;
    *) echo "Check your internet connection and try again. Or put update_linux.py from Lionel in the same folder as this file." ;;
  esac
  pause; exit 1
fi

export LIONEL_UPDATER_STUB="$self"
"$py" -I "$script" "$@"
rc=$?
pause
exit $rc
