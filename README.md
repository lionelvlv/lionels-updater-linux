# Lionel's Additions updater for Linux

Installs and updates **Lionel's Additions**, a modified All the Mods 10 pack (Minecraft 1.21.1, NeoForge), on Linux.
The Windows version and the pack's page live in [lionelvlv/lionels-updater](https://github.com/lionelvlv/lionels-updater)
([lionelvlv.github.io/lionels-updater](https://lionelvlv.github.io/lionels-updater/)).

## Use it

1. Download [`update-lionels-additions.sh`](https://raw.githubusercontent.com/lionelvlv/lionels-updater-linux/main/update-lionels-additions.sh)
   and keep it.
2. `chmod +x update-lionels-additions.sh`, then run `./update-lionels-additions.sh` (or double-click it: it opens a
   terminal for its questions).
3. Run it again whenever there is an update. It only downloads the files that changed.

`./update-lionels-additions.sh the.zip` uses an update zip you downloaded yourself.

Needs Python 3 (standard library only) and an ATM10 instance in a supported launcher: Modrinth (also the Flatpak),
ATLauncher, Prism Launcher. The game must be closed.

## What it does

The `.sh` is a small stub: on every run it fetches the newest `update_linux.py` from this repository and runs it (offline,
the copy beside it). `update_linux.py` follows the same steps as the Windows updater: finds your ATM10 instance,
downloads only the changed files of the update (each checked by SHA-1), removes files the update dropped (into a backup
folder), offers the optional mods and **potato mode** (shaders and visual mods off, the lowest settings; put back when you
turn it off), sets up Java and memory. It never touches your keybinds, options, worlds or screenshots, except the one
resource-pack line the pack needs.

## Tests

`python3 test_linux.py` runs the updater against a fake pack in a temporary folder (no network).

This repository is written by the pack's publish script; changes made here directly are overwritten.
