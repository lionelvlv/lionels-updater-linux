#!/usr/bin/env python3
# Lionel's Additions updater for Linux: the logic.
# The Linux port of update.ps1 and the .bat stub together (2026-10-20, Lionel: "make a version that works for linux").
# Run by update-lionels-additions.sh, which fetches the newest copy of this file from GitHub on every run (publish.ps1
# pushes it), so changes reach players the way update.ps1's do. Python 3.8+, standard library only.
#
# The same steps as update.ps1, numbered the same; what differs on Linux:
#   - the launchers' folders (also their Flatpak ones) and Prism Launcher, which many Linux players use;
#   - "is the game running" reads /proc (Linux does not lock open jars the way Windows does);
#   - Java is Azul's Linux build of the same 21.0.12.1; the launcher is not installed for the player (links only);
#   - no update check at each start yet (12b): lionel-check.jar starts the Windows .bat.
# Test-only switches: the LIONEL_UPDATER_* names of test.ps1 (TARGET, LAUNCHER, MODE, ZIP_URL, VERSION_URL, FULL_URL,
# JAVA_URL, FILES_URL, MEMORY, OPTIONAL, POTATO, RAM_GB, FREE_MB, NO_DRIVE_SCAN, NO_CLIPBOARD, NO_START, ATL_OPEN, IMPORT_TO).
import fnmatch, hashlib, os, platform, re, shutil, subprocess, sys, tarfile, tempfile, time, urllib.request, zipfile

MARK = "# Lionel's Additions updater for Linux: the logic."   # the .sh checks a downloaded copy for this line
DRIVE_ID = '1czcjd-xR4lmtCPN5fUlQ1XYYMoG7Z7Oo'                # the update zip (the .bat's DRIVE_ID)
VERSION_ID = '1B6Y0M7Evhnf-dArbi0-KD2ZICqmMAVZB'              # its version file
FULL_PACK_ID = '1WRkfq006ANIYAVzx9xawV1-zWi5Rv3H_'            # lionels-atm10-full.mrpack
GITHUB = os.environ.get('LIONEL_UPDATER_LOGIC_URL') or 'https://raw.githubusercontent.com/lionelvlv/lionels-updater/main'
env = os.environ.get


def drive(file_id):
    return f'https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t'


ZIP_URL = env('LIONEL_UPDATER_ZIP_URL') or drive(DRIVE_ID)
VERSION_URL = env('LIONEL_UPDATER_VERSION_URL') or drive(VERSION_ID)
# Per-file updates (2026-10-21): the public Cloudflare R2 bucket publish.ps1 fills (r2_publish.py). Set: only the files
# that changed are downloaded (manifest.txt, files/<sha1>); empty: the whole zip, as before. Same as the .bat's FILES_URL.
FILES_URL = 'https://pub-99b51619b26e447086dcdec6ff91a3f9.r2.dev'
if env('LIONEL_UPDATER_FILES_URL'):
    FILES_URL = '' if env('LIONEL_UPDATER_FILES_URL') == 'none' else env('LIONEL_UPDATER_FILES_URL')
if FILES_URL and not env('LIONEL_UPDATER_VERSION_URL'):
    VERSION_URL = FILES_URL + '/version.txt'
FULL_URL = '' if env('LIONEL_UPDATER_FULL_URL') == 'none' else (env('LIONEL_UPDATER_FULL_URL') or drive(FULL_PACK_ID))
HOME = os.path.expanduser('~')
STATE = os.path.join(env('XDG_CONFIG_HOME') or os.path.join(HOME, '.config'), 'lionels-updater')
DATA = env('XDG_DATA_HOME') or os.path.join(HOME, '.local', 'share')

# ---- the look: plain colours in a terminal, plain text otherwise ----
TTY = sys.stdout.isatty() and not env('LIONEL_UPDATER_PLAIN')


def paint(text, code):
    return f'\033[{code}m{text}\033[0m' if TTY else text


def say(text='', code=None):
    print(paint(text, code) if code else text, flush=True)


def section(title):
    say('\n' + paint('== ', '32') + paint(title, '1;32'))


def change(sign, text):
    say(f'  {paint(sign, {"+": "32", "~": "33", "-": "31"}[sign])} {text}')


def bar(label, fraction, detail=''):
    if not TTY:
        return
    width = 30
    full = int(max(0.0, min(1.0, fraction)) * width)
    sys.stdout.write(f'\r  {label} [' + paint('#' * full, '32') + '-' * (width - full) + f'] {detail}\033[K')
    sys.stdout.flush()


def clear_bar():
    if TTY:
        sys.stdout.write('\r\033[K')
        sys.stdout.flush()


class Stop(Exception):
    pass


def fail(message):
    clear_bar()
    raise Stop(message)


def ask(prompt):
    """One line from the player; None when there is no one to answer (end of input)."""
    try:
        return input(prompt)
    except EOFError:
        print()
        return None


def clean(answer):
    if not answer:
        return ''
    answer = answer.strip().strip('"').strip("'").strip()
    if answer.startswith('file://'):   # a folder dragged in from a file manager
        answer = urllib.request.url2pathname(answer[7:])
    answer = os.path.expanduser(answer)
    return answer.rstrip('/') if len(answer) > 1 else answer


def first_line(path):
    try:
        with open(path, encoding='utf-8-sig', errors='replace') as f:
            return f.readline().strip()
    except OSError:
        return ''


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text)


def read_text(path):
    # utf-8-sig: a BOM would stop ^ matching on the first line (update.ps1 reads them the same way)
    with open(path, encoding='utf-8-sig', errors='surrogateescape', newline='') as f:
        return f.read()


def save_text(path, text):
    with open(path, 'w', encoding='utf-8', errors='surrogateescape', newline='') as f:
        f.write(text)


# ---- downloads: plain links (Google Drive's usercontent one, GitHub, Azul), with size and speed ----
def download(url, dest, label):
    tmp = dest + '.part'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'lionels-updater-linux'})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, 'wb') as out:
            total = int(r.headers.get('Content-Length') or 0)
            got, start = 0, time.time()
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                speed = got / max(0.1, time.time() - start) / 1048576
                size = f'{got / 1048576:,.0f} of {total / 1048576:,.0f} MB' if total else f'{got / 1048576:,.0f} MB'
                bar(label, got / total if total else 0, f'{size}, {speed:.1f} MB/s')
        clear_bar()
        os.replace(tmp, dest)
        return True
    except Exception as e:
        clear_bar()
        say(f'  {label}: download failed ({e})', '33')
        if os.path.exists(tmp):
            os.remove(tmp)
        return False


def is_zip(path):
    try:
        with open(path, 'rb') as f:
            return f.read(2) == b'PK'
    except OSError:
        return False


def free_mb(path):
    if env('LIONEL_UPDATER_FREE_MB'):
        return int(env('LIONEL_UPDATER_FREE_MB'))
    while path and not os.path.isdir(path):
        path = os.path.dirname(path)
    return shutil.disk_usage(path or '/').free // 1048576


def unpack(zip_path, into):
    with zipfile.ZipFile(zip_path) as z:
        root = os.path.realpath(into)
        for info in z.infolist():
            name = info.filename.replace('\\', '/')
            dest = os.path.realpath(os.path.join(root, name))
            if dest != root and not dest.startswith(root + os.sep):
                raise zipfile.BadZipFile(f'unsafe path in the zip: {name}')
        z.extractall(root)


def copy_clipboard(text):
    if env('LIONEL_UPDATER_NO_CLIPBOARD'):
        return False
    tools = [['wl-copy']] if env('WAYLAND_DISPLAY') else []
    tools += [['xclip', '-selection', 'clipboard'], ['xsel', '--clipboard', '--input']]
    for cmd in tools:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode(), timeout=5, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception:
                pass
    return False


def open_thing(target):
    if env('LIONEL_UPDATER_NO_START') or not shutil.which('xdg-open'):
        return False
    try:
        subprocess.Popen(['xdg-open', target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


# ---- processes, from /proc ----
def processes():
    for pid in os.listdir('/proc'):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                argv = [a.decode(errors='replace') for a in f.read().split(b'\0') if a]
        except OSError:
            continue
        if argv:
            try:
                cwd = os.readlink(f'/proc/{pid}/cwd')
            except OSError:
                cwd = ''
            yield argv, cwd


def launcher_running(launcher):
    if launcher == 'ATLauncher' and env('LIONEL_UPDATER_ATL_OPEN'):
        return env('LIONEL_UPDATER_ATL_OPEN') == '1'   # test switch
    for argv, _ in processes():
        exe = os.path.basename(argv[0]).lower()
        if launcher == 'ATLauncher' and (exe == 'atlauncher' or any(a.lower().endswith('atlauncher.jar') for a in argv)):
            return True
        if launcher == 'Prism' and exe in ('prismlauncher', 'multimc'):
            return True
        if launcher == 'Modrinth' and exe in ('modrinth-app', 'modrinth app', 'modrinthapp', 'theseus'):
            return True
    return False


def game_running(target):
    real = os.path.realpath(target)
    for argv, cwd in processes():
        if not os.path.basename(argv[0]).startswith('java'):
            continue
        if cwd and os.path.realpath(cwd) == real:
            return True
        if any(real in a or target in a for a in argv[1:]):
            return True
    return False


# ---- paths ----
# Players' own settings. Never written, whatever the zip contains. Keybinds live in options.txt.
PROTECTED = re.compile(r'^(options.*\.txt|servers\.dat.*|saves/|journeymap/|shaderpacks/|screenshots/|config/[^/]*keybind)', re.I)


def resolve_safe(target, rel):
    """A relative path from the zip or a list file, checked before it is used against the player's folder."""
    rel = rel.strip().replace('\\', '/')
    if not rel or re.search(r'(^|/)\.\.(/|$)', rel) or rel.startswith('/') or ':' in rel:
        raise ValueError(f'Unsafe path refused: {rel}')
    if PROTECTED.search(rel):
        raise ValueError(f'Refusing to touch a player settings file: {rel}')
    if re.search(r'\*.*/', rel):
        raise ValueError(f'A * may only stand in a file name: {rel}')
    if re.match(r'^(mods|config|kubejs|resourcepacks|defaultconfigs|logs|crash-reports|\.)/*$', rel, re.I):
        raise ValueError(f'Refusing to act on a whole pack folder: {rel}')
    return os.path.join(target, rel)


def get_files(root):
    out = []
    for d, _, names in os.walk(root):
        for n in names:
            out.append(os.path.relpath(os.path.join(d, n), root).replace(os.sep, '/'))
    return sorted(out)


def sha1(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def same_file(a, b):
    return os.path.getsize(a) == os.path.getsize(b) and sha1(a) == sha1(b)


def copy_to(src, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(src, dest)


def move_to(src, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        os.remove(dest)
    shutil.move(src, dest)


def read_list(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        return [l.strip() for l in f if l.strip() and not l.lstrip().startswith('#')]


def test_pack(p):
    if not p:
        return False
    bcc = os.path.join(p, 'config', 'bcc-common.toml')
    if not (os.path.isdir(os.path.join(p, 'mods')) and os.path.isfile(bcc)):
        return False
    try:
        return 'All the Mods 10' in read_text(bcc)
    except OSError:
        return False


# ---- 1. which launcher, which ATM10 folder ----
LAUNCHERS = ['ATLauncher', 'Modrinth', 'Prism']
NAMES = {'ATLauncher': 'ATLauncher', 'Modrinth': 'Modrinth app', 'Prism': 'Prism Launcher (or MultiMC)'}
PAGES = {'ATLauncher': 'https://atlauncher.com/downloads', 'Modrinth': 'https://modrinth.com/app',
         'Prism': 'https://prismlauncher.org/download/linux'}
FLATPAK = os.path.join(HOME, '.var', 'app')


def modrinth_dirs():
    return [os.path.join(DATA, 'ModrinthApp'), os.path.join(DATA, 'com.modrinth.theseus'),
            os.path.join(FLATPAK, 'com.modrinth.ModrinthApp', 'data', 'ModrinthApp')]


def find_packs():
    """ATM10 instances in the usual launcher folders, Flatpak ones too. The Modrinth app may keep its profiles anywhere,
    and that folder is only written in its app.db, so paths are read out of that file's bytes (as update.ps1 does)."""
    roots = []
    for m in modrinth_dirs():
        roots.append((os.path.join(m, 'profiles'), 'Modrinth'))
    probed = set()
    for m in modrinth_dirs():
        for db in ('app.db', 'app.db-wal'):
            try:
                with open(os.path.join(m, db), 'rb') as f:
                    data = f.read()
            except OSError:
                continue
            for hit in re.finditer(rb'/(?:home|mnt|media|run/media|opt|srv|data|games|Games)/[^\x00-\x1f"<>|*?]{1,200}', data):
                p = hit.group().decode('latin-1')
                while len(p) > 1 and p not in probed:
                    probed.add(p)
                    if os.path.isdir(os.path.join(p, 'profiles')):
                        roots.append((os.path.join(p, 'profiles'), 'Modrinth'))
                        break
                    p = os.path.dirname(p)
    for a in (os.path.join(DATA, 'atlauncher'), os.path.join(DATA, 'ATLauncher'), os.path.join(HOME, '.atlauncher'),
              os.path.join(HOME, 'ATLauncher'), os.path.join(HOME, 'Games', 'ATLauncher'),
              os.path.join(HOME, 'Downloads', 'ATLauncher'), os.path.join(FLATPAK, 'com.atlauncher.ATLauncher', 'data')):
        roots.append((os.path.join(a, 'instances'), 'ATLauncher'))
    for p in (os.path.join(DATA, 'PrismLauncher'), os.path.join(DATA, 'multimc'), os.path.join(HOME, '.local', 'share', 'polymc'),
              os.path.join(FLATPAK, 'org.prismlauncher.PrismLauncher', 'data', 'PrismLauncher')):
        roots.append((os.path.join(p, 'instances'), 'Prism'))
    if env('LIONEL_UPDATER_NO_DRIVE_SCAN'):   # tests: a real pack on this PC is never offered to them
        roots = []
    found, seen = [], set()
    for root, kind in roots:
        try:
            insts = sorted(e.path for e in os.scandir(root) if e.is_dir())
        except OSError:
            continue
        for inst in insts:
            for p in (inst, os.path.join(inst, 'minecraft'), os.path.join(inst, '.minecraft'), os.path.join(inst, 'instance')):
                real = os.path.realpath(p)
                if real not in seen and test_pack(p):
                    seen.add(real)
                    found.append((p, kind))
    return found


def choose(prompt, options, default=None):
    """A numbered question; returns the 1-based number picked. Enter alone: default. Q or no input: stop."""
    while True:
        for i, o in enumerate(options, 1):
            say(f'  {i}) {o}')
        hint = f' (Enter: {default})' if default else ''
        answer = ask(f'{prompt}{hint}, or Q to stop: ')
        if answer is None or clean(answer).lower() == 'q':
            fail('Stopped. Nothing was changed.')
        answer = clean(answer)
        if not answer and default:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer)
        say(f"'{answer}' is not one of the numbers above.", '33')


def pick_launcher():
    seen = os.path.join(STATE, 'launcher.txt')
    last = first_line(seen)
    launcher = env('LIONEL_UPDATER_LAUNCHER')
    if launcher not in LAUNCHERS:
        say('\nWhich launcher do you play ATM10 in?')
        default = LAUNCHERS.index(last) + 1 if last in LAUNCHERS else None
        launcher = LAUNCHERS[choose('Type a number and press Enter', [NAMES[l] for l in LAUNCHERS], default) - 1]
    write_text(seen, launcher + '\n')
    return launcher


def pick_instance(launcher, remembered):
    say(f'\nLooking for ATM10 in {NAMES[launcher]}...')
    packs = [p for p, kind in find_packs() if kind == launcher]
    default = ''
    if remembered in packs:
        packs.remove(remembered)
        packs.insert(0, remembered)
        default = remembered
    elif len(packs) == 1:
        default = packs[0]
    while True:
        say()
        if packs:
            say("Which one is the ATM10 you play on Lionel's server?")
            for i, p in enumerate(packs, 1):
                say(f'  {i}) {p}' + ('   (Enter)' if p == default else ''))
        else:
            say(f"No ATM10 instance found in {NAMES[launcher]}'s usual folders.")
        say('  Or paste the folder\'s path (the one containing "mods" and "config"; dragging it here works too), Q to stop.')
        raw = ask('Your choice: ')
        answer = clean(raw)
        if not answer and default:
            return default
        if raw is None or not answer or answer.lower() == 'q':
            fail('No folder chosen. Nothing was changed.')
        if answer.isdigit() and 1 <= int(answer) <= len(packs):
            return packs[int(answer) - 1]
        for p in (answer, os.path.join(answer, 'minecraft'), os.path.join(answer, '.minecraft')):
            if test_pack(p):
                return p
        say(f'That folder is not an All the Mods 10 instance: {answer}', '33')


def sign_in_steps(launcher):
    say(f'\nSign in to Minecraft in {NAMES[launcher]} first, if you have not:', '36')
    if launcher == 'ATLauncher':
        say('  Accounts tab on the right > "Login with Microsoft", sign in in the browser with the account that owns')
        say('  Minecraft: Java Edition. Your Minecraft name shows at the bottom right when it worked.')
    elif launcher == 'Modrinth':
        say('  The account button in the bottom left > "Add account", sign in with the Microsoft account that owns')
        say('  Minecraft: Java Edition. (A Modrinth account is something else; the pack does not need one.)')
    else:
        say('  Top right "Accounts" > "Manage accounts" > "Add Microsoft", sign in with the account that owns Minecraft.')


def install_fresh(launcher, work):
    """The whole pack is downloaded, the player imports it (no launcher can be told to from outside), and the instance
    that appears is then updated and set up like any other."""
    if not FULL_URL:
        fail('A fresh install is not available yet: Lionel has not uploaded the whole pack. Ask him. Nothing was changed.')
    if free_mb(work) < 3500:
        fail(f'Not enough free space for the whole pack in {work}: {free_mb(work):,} MB free, about 3,500 MB needed.')
    pack = os.path.join(work, 'Lionels-ATM10.mrpack')
    say('\nDownloading the whole pack (about 2.7 GB; this takes a while)...')
    if not (download(FULL_URL, pack, 'The whole pack') and is_zip(pack)):
        fail('The pack could not be downloaded. Check your internet connection and free space, and try again. Nothing was changed.')
    before = {p for p, k in find_packs() if k == launcher}
    sign_in_steps(launcher)
    say(f'\nNow import it into {NAMES[launcher]}:', '36')
    if launcher == 'ATLauncher':
        say('  Its "Import" tab > "Browse", choose the file below, then "Import". Wait until it has finished installing.')
    elif launcher == 'Modrinth':
        say('  The + (Create new instance) on the left > "From file", choose the file below. Wait until it has installed.')
    else:
        say('  "Add Instance" > "Import" on the left, "Browse" to the file below, OK. Wait until it has installed.')
    say(f'  The file: {pack}')
    if copy_clipboard(pack):
        say('  (Its path is copied: paste it in the file window with Ctrl+L, Ctrl+V.)')
    say('  Keep this window open meanwhile: the file is deleted when the updater finishes.')
    while True:
        raw = ask("\nWhen the import has finished, press Enter here (or paste the new instance's folder, or Q to stop): ")
        answer = clean(raw)
        if answer.lower() == 'q':
            fail('Stopped. Your launcher may already have the new instance: run the updater again and choose Update for it.')
        if env('LIONEL_UPDATER_IMPORT_TO'):   # tests: does what the launcher's import does with the pack's files
            tmp = os.path.join(work, 'import-sim')
            unpack(pack, tmp)
            os.makedirs(os.path.dirname(env('LIONEL_UPDATER_IMPORT_TO')), exist_ok=True)
            shutil.move(os.path.join(tmp, 'overrides'), env('LIONEL_UPDATER_IMPORT_TO'))
            shutil.rmtree(tmp)
        if answer:
            for p in (answer, os.path.join(answer, 'minecraft'), os.path.join(answer, '.minecraft')):
                if test_pack(p):
                    return p
            say(f'That folder is not an All the Mods 10 instance: {answer}', '33')
            continue
        new = [p for p, k in find_packs() if k == launcher and p not in before]
        if len(new) == 1:
            return new[0]
        if len(new) > 1:
            return new[choose('More than one new ATM10 instance. Type the number of the one just imported', new) - 1]
        if raw is None:
            fail('No new ATM10 instance found. Run the updater again once the import has finished, and choose Update.')
        say(f'No new ATM10 instance in {NAMES[launcher]} yet. Is the import finished? If it is somewhere unusual, paste its folder.', '33')


# ---- 3b/5c: mod ids from a jar ----
_mod_ids = {}


def mod_ids(jar):
    if jar in _mod_ids:
        return _mod_ids[jar]
    ids = []
    try:
        with zipfile.ZipFile(jar) as z:
            for name in ('META-INF/neoforge.mods.toml', 'META-INF/mods.toml'):
                try:
                    text = z.read(name).decode('utf-8', errors='replace')
                except KeyError:
                    continue
                in_mods = False
                for line in text.split('\n'):
                    if re.match(r'^\s*\[\[\s*mods\s*\]\]', line):
                        in_mods = True
                        continue
                    if re.match(r'^\s*\[', line):
                        in_mods = False
                        continue
                    m = re.match(r'^\s*modId\s*=\s*"([^"]+)"', line)
                    if in_mods and m:
                        ids.append(m.group(1))
                        in_mods = False
                break
    except Exception:
        pass
    _mod_ids[jar] = ids
    return ids


def jars(folder, suffix='.jar'):
    try:
        return sorted(e.path for e in os.scandir(folder) if e.is_file() and e.name.lower().endswith(suffix))
    except OSError:
        return []


def edit_once(target, rel, edits, said):
    """Each pattern's first group is kept and what follows it replaced, once, and only from the pack's default. The
    backup is the marker, so whatever the player sets afterwards stays (update.ps1 steps 10 and 11)."""
    path = os.path.join(target, rel)
    if not os.path.isfile(path) or os.path.exists(path + '.bak-lionel'):
        return
    before = text = read_text(path)
    for pattern, value in edits:
        m = re.search(pattern, text)
        if m:
            text = text[:m.start()] + m.group(1) + value + text[m.end():]
    if text != before:
        shutil.copy2(path, path + '.bak-lionel')
        save_text(path, text)
        change('~', f'{rel}: {said}')


def json_text(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def set_json_key(text, key, value):
    """One key of ATLauncher's instance.json "launcher" section, replaced where it is or added at the section's start. A
    regex, not json.dump: the file is megabytes of library lists, best left as ATLauncher wrote them."""
    rx = re.compile('"' + key + r'"\s*:\s*(?:"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|true|false|null)')
    if rx.search(text):
        return rx.sub(lambda _: f'"{key}": {value}', text, count=1)
    at = re.search(r'"launcher"\s*:\s*\{', text)
    if not at:
        raise ValueError('instance.json has no "launcher" section')
    return text[:at.end()] + f'\n    "{key}": {value},' + text[at.end():]


def set_cfg_keys(text, keys):
    """Keys of Prism's instance.cfg (an INI file, everything under [General]): replaced where they are, else added."""
    nl = '\r\n' if '\r\n' in text else '\n'
    missing = ''
    for key, value in keys.items():
        rx = re.compile(r'(?m)^' + re.escape(key) + r'=.*?(?=\r?$)')
        if rx.search(text):
            text = rx.sub(lambda _: f'{key}={value}', text, count=1)
        else:
            missing += f'{key}={value}{nl}'
    at = re.search(r'(?m)^\[General\][^\n]*\n', text)
    if not at:
        return f'[General]{nl}{missing}' + text
    return text[:at.end()] + missing + text[at.end():]


# ---- potato mode (step 5p; update.ps1 has the same, potato.txt the list) ----
POTATO = False   # set by potato_mode(): the optional mods (5c) and the memory (12) follow it
PACK_ENTRY = r'"((?:[^"\\]|\\.)*)"'


def find_setting(text, kind, sec, key):
    """Where a setting's value sits in a file's text: a match whose group 1 is the value, or None."""
    if kind == 'kv':
        return re.search(r'(?m)^' + re.escape(key) + r':(.*?)(?=\r?$)', text)
    if kind == 'json':
        start = 0
        if sec != '-':
            m = re.search('"' + re.escape(sec) + r'"\s*:\s*\{', text)
            if not m:
                return None
            start = m.end()
        return re.compile('"' + re.escape(key) + r'"\s*:\s*("(?:[^"\\]|\\.)*"|[-+\d.eE]+|true|false|null)').search(text, start)
    if kind == 'toml':
        after = 0   # section "-": a key at the top of the file, before the first [section]
        if sec != '-':
            m = re.search(r'(?m)^[ \t]*\[' + re.escape(sec) + r'\][ \t]*(?=\r?$)', text)
            if not m:
                return None
            after = m.end()
        nxt = re.compile(r'(?m)^[ \t]*\[').search(text, after)
        end = nxt.start() if nxt else len(text)
        k = re.compile(r'(?m)^[ \t]*' + re.escape(key) + r'[ \t]*=[ \t]*(.*?)[ \t]*(?=\r?$)').search(text, after)
        return k if k and k.start() < end else None
    return None


def kind_of(rel):
    return 'kv' if rel == 'options.txt' else 'toml' if rel.endswith('.toml') else 'json'


def pack_rule(entry, rule):
    return entry.startswith(rule[:-1]) if rule.endswith('*') else entry == rule


def potato_mode(target, src, n):
    """5p. Potato mode: potato.txt's mods off, its resource packs out of / into the list, its settings set; everything
    it replaced written down in lionels-updater-potato.txt and put back when it is switched off (a setting the player
    changed in the meantime stays theirs). Asked every run, Enter keeps; first run: on with less than 16 GB of RAM."""
    global POTATO
    mods, packs, sets = {}, [], []
    for line in read_list(os.path.join(src, 'potato.txt')):
        p = line.split('|')
        if p[0] == 'mod' and len(p) >= 3:
            mods[p[1].strip()] = p[2].strip()
        elif p[0] == 'pack' and len(p) >= 3:
            packs.append((p[1], p[2].strip()))
        elif p[0] == 'set' and len(p) >= 6:
            sets.append((p[1], p[2], p[3], p[4], '|'.join(p[5:])))
    if not mods and not sets:
        return
    section('Potato mode')
    state = os.path.join(target, 'lionels-updater-potato.txt')
    was, rec_mods, rec_packs, rec_now, rec_sets = False, [], None, None, []
    if os.path.isfile(state):
        for l in read_text(state).splitlines():
            f = l.split('\t')
            if f[0] == 'potato':
                was = f[1] == 'on'
            elif f[0] == 'mod':
                rec_mods.append(f[1])
            elif f[0] == 'packs':
                rec_packs = f[1]
            elif f[0] == 'packsnow':
                rec_now = f[1]
            elif f[0] == 'set' and len(f) >= 6:
                rec_sets.append(f[1:6])
    ram = ram_gb()
    on = was if os.path.isfile(state) else ram < 16
    say('\nPotato mode, for weak PCs: shaders and other visual mods off, the lowest settings (render distance 3,')
    say('Fast graphics, no particles, no sky, mobs and blocks drawn only close by), smaller textures, 8 GB.')
    say('You still join the server as normal. Switching it off later puts your own settings back.')
    say(f"This PC has {ram} GB of RAM. Potato mode is {'ON' if on else 'OFF'}.")
    answer = (env('LIONEL_UPDATER_POTATO') or ask('  Press Enter to keep it, or type Y (on) or N (off) and press Enter: ') or '').strip().upper()
    if answer in ('Y', 'YES', 'ON'):
        on = True
    elif answer in ('N', 'NO', 'OFF'):
        on = False
    elif answer:
        say(f"  '{answer}' is not Y or N: potato mode stays {'on' if on else 'off'}.", '33')
    mods_dir = os.path.join(target, 'mods')
    options = os.path.join(target, 'options.txt')
    if on:
        for j in jars(mods_dir):
            hit = [i for i in mod_ids(j) if i in mods]
            if not hit:
                continue
            if os.path.exists(j + '.disabled'):
                os.remove(j + '.disabled')
            move_to(j, j + '.disabled')
            rel = 'mods/' + os.path.basename(j)
            if rel not in rec_mods:
                rec_mods.append(rel)
            n['removed'] += 1
            change('-', f'{rel}  ({mods[hit[0]]}: off for potato mode, renamed .jar.disabled)')
        if os.path.isfile(options):
            text = read_text(options)
            m = re.search(r'(?m)^resourcePacks:\[(.*?)\](?=\r?$)', text)
            if m:
                entries = re.findall(PACK_ENTRY, m.group(1))
                keep = [e for e in entries if not any(r[1] == 'off' and pack_rule(e, r[0]) for r in packs)]
                for rule, what in packs:
                    if what == 'on' and rule not in keep and rule.startswith('file/') and \
                            os.path.exists(os.path.join(target, 'resourcepacks', rule[5:])):
                        keep.append(rule)
                inside = ','.join(f'"{e}"' for e in keep)
                if inside != m.group(1):
                    if not os.path.exists(options + '.bak-lionel-potato'):
                        shutil.copyfile(options, options + '.bak-lionel-potato')
                    if rec_packs is None:
                        rec_packs = m.group(1)
                    save_text(options, text[:m.start(1)] + inside + text[m.end(1):])
                    gone, new = [e for e in entries if e not in keep], [e for e in keep if e not in entries]
                    change('~', 'options.txt: resource packs for potato mode' + (f"; off: {', '.join(gone)}" if gone else '')
                           + (f"; on: {', '.join(new)}" if new else ''))
                rec_now = inside
        changed = {}
        for rel, kind, sec, key, value in sets:
            path = os.path.join(target, rel)
            if not os.path.isfile(path) or any(r[0] == rel and r[1] == sec and r[2] == key for r in rec_sets):
                continue
            text = read_text(path)
            m = find_setting(text, kind, sec, key)
            if not m:
                continue
            rec_sets.append([rel, sec, key, m.group(1), value])
            if m.group(1) == value:
                continue
            if not os.path.exists(path + '.bak-lionel-potato'):
                shutil.copyfile(path, path + '.bak-lionel-potato')
            save_text(path, text[:m.start(1)] + value + text[m.end(1):])
            changed[rel] = changed.get(rel, 0) + 1
        for rel, k in changed.items():
            change('~', f'{rel}: {k} setting(s) set for potato mode (your old values are kept to put back)')
    elif was:
        for rel in rec_mods:
            j = resolve_safe(target, rel)
            if os.path.isfile(j + '.disabled') and not os.path.exists(j):
                move_to(j + '.disabled', j)
                n['added'] += 1
                change('+', f'{rel}  (potato mode off: switched back on)')
        if os.path.isfile(options) and rec_packs is not None:
            text = read_text(options)
            m = re.search(r'(?m)^resourcePacks:\[(.*?)\](?=\r?$)', text)
            if m:
                if m.group(1) == rec_now:
                    back = rec_packs
                else:   # the player changed packs meanwhile: theirs stay, potato's go, the ones it took out come back
                    before, now = re.findall(PACK_ENTRY, rec_packs), re.findall(PACK_ENTRY, rec_now or '')
                    entries = [e for e in re.findall(PACK_ENTRY, m.group(1)) if e in before or e not in now]
                    entries += [e for e in before if e not in entries]
                    back = ','.join(f'"{e}"' for e in entries)
                if back != m.group(1):
                    save_text(options, text[:m.start(1)] + back + text[m.end(1):])
                    change('~', 'options.txt: your resource packs as they were before potato mode')
        restored = {}
        for rel, sec, key, old, new in rec_sets:
            path = os.path.join(target, rel)
            if not os.path.isfile(path):
                continue
            text = read_text(path)
            m = find_setting(text, kind_of(rel), sec, key)
            if not m or m.group(1) != new or old == new:
                continue   # changed by the player since: theirs
            save_text(path, text[:m.start(1)] + old + text[m.end(1):])
            restored[rel] = restored.get(rel, 0) + 1
        for rel, k in restored.items():
            change('~', f'{rel}: {k} setting(s) back to yours (potato mode off)')
        rec_mods, rec_packs, rec_now, rec_sets = [], None, None, []
    lines = [f"potato\t{'on' if on else 'off'}"] + [f'mod\t{r}' for r in rec_mods]
    if rec_packs is not None:
        lines += [f'packs\t{rec_packs}', f'packsnow\t{rec_now}']
    lines += ['set\t' + '\t'.join(r) for r in rec_sets]
    save_text(state, '\n'.join(lines) + '\n')
    if on:
        say('  Potato mode is on.')
    elif was:
        say('  Potato mode is off: everything it changed is back.')
    POTATO = on



# ---- per-file updates (R2): the manifest and the files it names ----
def fetch_quiet(url, dest):
    tmp = dest + '.part'
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        # A User-Agent of our own: Cloudflare's r2.dev answers Python's default one with 403 (checked 2026-10-21)
        req = urllib.request.Request(url, headers={'User-Agent': 'lionels-updater-linux'})
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, 'wb') as f:
            shutil.copyfileobj(r, f, 1 << 20)
        return tmp
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        return None


def read_manifest(src):
    """manifest.txt and version.txt from the bucket into src; the manifest's entries, or None."""
    for name in ('manifest.txt', 'version.txt'):
        t = fetch_quiet(f'{FILES_URL}/{name}', os.path.join(src, name))
        if not t:
            return None
        os.replace(t, os.path.join(src, name))
    out = []
    for line in read_text(os.path.join(src, 'manifest.txt')).splitlines():
        p = line.split('|')
        if len(p) == 4 and p[0] in ('overwrite', 'if-missing') and re.match(r'^[0-9a-f]{40}$', p[2]):
            out.append({'set': p[0], 'rel': p[1], 'sha': p[2], 'size': int(p[3])})
    return out if any(e['set'] == 'overwrite' for e in out) else None


def get_manifest_files(items):
    """Downloads entries (dicts with sha, size, to) six at a time, each checked against its SHA-1 before it replaces
    anything. Returns the ones that failed."""
    if not items:
        return []
    from concurrent.futures import ThreadPoolExecutor
    say(f"  Downloading {len(items)} file(s), {sum(i['size'] for i in items) / 1048576:.1f} MB...")

    def one(it):
        tmp = fetch_quiet(f"{FILES_URL}/files/{it['sha']}", it['to'])
        if tmp and sha1(tmp) == it['sha']:
            os.replace(tmp, it['to'])
            return None
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
        return it
    with ThreadPoolExecutor(6) as pool:
        return [r for r in pool.map(one, items) if r]


def ram_gb():
    if env('LIONEL_UPDATER_RAM_GB'):
        return int(env('LIONEL_UPDATER_RAM_GB'))
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    return round(int(line.split()[1]) / 1048576)
    except OSError:
        pass
    return 16


def read_steps(steps, picture, src):
    """Steps for the player to do in a launcher, one at a time, each value copied where a clipboard tool is installed."""
    say('  At any step, type P and press Enter to see a picture of the page, numbered like the steps.')
    for i, (text, value) in enumerate(steps, 1):
        say(f'\n  Step {i} of {len(steps)}: {text}')
        if value:
            say(f'     {value}', '1')
            if copy_clipboard(value):
                say('     (Already copied: just paste.)')
        while True:
            answer = ask('     Press Enter when done (P: picture). ')
            if answer and answer.strip().lower() == 'p':
                local = os.path.join(src, 'guide', picture)
                where = local if os.path.isfile(local) else f'{GITHUB}/guide/{picture}'
                say('     (The picture opened. Its numbers are these step numbers.)' if open_thing(where) else f'     (The picture: {where})')
                continue
            break


def main():
    work = None
    try:
        os.makedirs(STATE, exist_ok=True)
        say(paint("\n  Lionel's Additions", '1;32') + paint('  updater for Linux', '32'))
        dropped = sys.argv[1] if len(sys.argv) > 1 else ''   # a zip given on the command line: used instead of downloading
        if dropped and not is_zip(dropped):
            fail(f'Not a zip file: {dropped}')

        launcher = pick_launcher()
        target = env('LIONEL_UPDATER_TARGET') or ''
        mode = env('LIONEL_UPDATER_MODE') or ('update' if target or dropped else '')
        if mode not in ('update', 'fresh'):
            say('\nWhat would you like to do?')
            mode = ['update', 'fresh'][choose('Type 1 or 2 and press Enter', [
                f'Update the ATM10 you already have in {NAMES[launcher]}',
                f'Install the whole pack fresh, as a new {NAMES[launcher]} instance (about 2.7 GB to download)'], 1) - 1]

        # Where the downloads go: the temporary folder, or the one the player chose last time when that was too full.
        base_file = os.path.join(STATE, 'temp-folder.txt')
        base = first_line(base_file) or tempfile.gettempdir()
        if not os.path.isdir(base):
            base = tempfile.gettempdir()
        need = 1000 if dropped else (4500 if mode == 'fresh' else (300 if FILES_URL else 2000))
        while free_mb(base) < need:
            say(f'\nNot enough free space for the download in {base}: {free_mb(base):,} MB free, about {need:,} MB needed.')
            say('It is only used during the update and removed afterwards.')
            answer = clean(ask('Paste a folder on a drive with more free space and press Enter, or just Enter to stop: '))
            if not answer:
                fail('Stopped. Nothing was changed.')
            if not os.path.isdir(answer):
                say(f'That folder does not exist: {answer}', '33')
                continue
            base = answer
            write_text(base_file, base + '\n')
        work = os.path.join(base, 'lionels-updater')
        shutil.rmtree(work, ignore_errors=True)   # leftovers from a run that was interrupted
        os.makedirs(work)

        remembered = first_line(os.path.join(STATE, 'path.txt'))
        if mode == 'fresh':
            target = install_fresh(launcher, work)
        if not test_pack(target):
            target = pick_instance(launcher, remembered)
        target = target.rstrip('/')
        write_text(os.path.join(STATE, 'path.txt'), target + '\n')

        # The update itself. Nothing new (the instance's record matches the version file online)? Then no big download.
        latest_file = os.path.join(work, 'latest.txt')
        have = first_line(os.path.join(target, 'lionels-updater-version.txt'))
        latest = first_line(latest_file) if download(VERSION_URL, latest_file, 'Version') else ''
        if latest.startswith('<'):
            latest = ''   # an error page, not the version file
        src = os.path.join(work, 'files')
        if dropped:
            unpack(dropped, src)
        else:
            if mode == 'fresh':
                in_pack = first_line(os.path.join(target, 'lionels-updater-pack-version.txt'))
                if latest and in_pack == latest:
                    say(f'\nThe whole pack already has the latest update ({latest}): nothing more to download.')
                    src = None
            elif latest and have == latest:
                answer = ask('\nYou already have the latest update. Press Enter to close, or type R and Enter to install it again: ')
                if not answer or answer.strip().lower() != 'r':
                    return 0
            if src and FILES_URL and not env('LIONEL_UPDATER_FORCE_ZIP'):
                os.makedirs(src, exist_ok=True)
                manifest = read_manifest(src)
                if manifest is not None:
                    for f in ('delete.txt', 'optional.txt', 'potato.txt', 'java/resolver-patch.jar'):
                        os.makedirs(os.path.dirname(os.path.join(src, f)), exist_ok=True)
                        download(f'{GITHUB}/{f}', os.path.join(src, f), f)
                    return apply(launcher, mode, target, src, manifest)
                say('\nThe file list of the update could not be read; the whole update zip is used instead.', '33')
            if src:
                say('\nDownloading the latest update (about 800 MB)...')
                zip_path = os.path.join(work, 'update.zip')
                if not (download(ZIP_URL, zip_path, 'The update') and is_zip(zip_path)):
                    fail('The update could not be downloaded or is not a valid zip. Check your internet connection and\n'
                         'try again. If it keeps failing, download the zip in your browser and run:\n'
                         f'  {env("LIONEL_UPDATER_STUB") or "./update-lionels-additions.sh"} /path/to/the.zip')
                try:
                    unpack(zip_path, src)
                except zipfile.BadZipFile as e:
                    fail(f'The update is not a valid zip ({e}). Nothing was changed.')
                os.remove(zip_path)
                if not os.path.isdir(os.path.join(src, 'overwrite')):
                    fail('The update zip has no "overwrite" folder: not an update of Lionel\'s Additions. Nothing was changed.')
        if src is None:
            # A current whole pack: only the small files (optional mods' list, Java patch, pictures) from GitHub.
            src = os.path.join(work, 'files')
            for f in ('delete.txt', 'optional.txt', 'potato.txt', 'java/resolver-patch.jar'):
                os.makedirs(os.path.dirname(os.path.join(src, f)), exist_ok=True)
                download(f'{GITHUB}/{f}', os.path.join(src, f), f)
            if latest:
                write_text(os.path.join(src, 'version.txt'), latest + '\n')
        return apply(launcher, mode, target, src)
    except Stop as e:
        say(f'\n{e}', '31')
        return 1
    except KeyboardInterrupt:
        say('\nStopped.', '31')
        return 1
    finally:
        if work and os.path.isdir(work):
            shutil.rmtree(work, ignore_errors=True)
            say('Temporary files removed.' if not os.path.isdir(work) else f'Could not remove temporary files in {work}')


def apply(launcher, mode, target, src, manifest=None):
    have_files = os.path.isdir(os.path.join(src, 'overwrite')) or manifest is not None
    ow_list = [e for e in manifest if e['set'] == 'overwrite'] if manifest is not None else []
    im_list = [e for e in manifest if e['set'] == 'if-missing'] if manifest is not None else []
    label = first_line(os.path.join(src, 'version.txt')) or 'unknown'
    section(f"Lionel's Additions, update {label}")
    say(f'  Folder: {target}\n')
    m = re.search(r'modpackVersion\s*=\s*"([^"]+)"', read_text(os.path.join(target, 'config', 'bcc-common.toml')))
    if m and m.group(1) != '8.1':
        say(f'Note: this is ATM10 version {m.group(1)}. These files were made for 8.1.\n', '33')

    # 2. Updating underneath a running game would leave a half-changed pack.
    if game_running(target):
        fail('Minecraft looks like it is running from this folder. Close the game and run the updater again. Nothing was changed.')

    # Check every path this update names before changing anything, so a bad update changes nothing at all.
    record = os.path.join(target, 'lionels-updater-installed.txt')
    overwrite, if_missing = os.path.join(src, 'overwrite'), os.path.join(src, 'if-missing')
    named = ([e['rel'] for e in manifest] if manifest is not None else get_files(overwrite) + get_files(if_missing)) + \
        read_list(os.path.join(src, 'delete.txt')) + read_list(record)
    optional = []
    for line in read_list(os.path.join(src, 'optional.txt')):
        p = line.split('|')
        if len(p) < 6:
            continue
        files = [tuple(x.strip() for x in f.split('>')) for f in p[5].split(';') if len(f.split('>')) == 3]
        optional.append({'id': p[0].strip(), 'name': p[1].strip(), 'about': p[2].strip(), 'default': p[3].strip() == 'on',
                         'ids': [x.strip() for x in p[4].split(',') if x.strip()],
                         'files': [(a, b, c.lower()) for a, b, c in files]})
    optional_paths = {f[0] for m in optional for f in m['files']}
    named += list(optional_paths)
    try:
        for rel in named:
            resolve_safe(target, rel)
    except ValueError as e:
        fail(f'{e}\nThis update is faulty. Nothing was changed. Tell Lionel.')

    # Room on the ATM10 drive for what this update copies (a size that differs means a copy; 200 MB to spare).
    need = 200 * 1048576
    sizes = [(e['rel'], e['size'], e['set'] == 'overwrite') for e in manifest] if manifest is not None else \
        [(rel, os.path.getsize(os.path.join(root, rel)), over) for root, over in ((overwrite, True), (if_missing, False))
         for rel in get_files(root)]
    for rel, size, over in sizes:
        dest = os.path.join(target, rel)
        need += size if not os.path.exists(dest) else (max(0, size - os.path.getsize(dest)) if over else 0)
    if free_mb(target) * 1048576 < need:
        fail(f'Not enough free space on the drive of your ATM10 folder: {free_mb(target):,} MB free, about {need // 1048576:,} MB needed.\n'
             'Free some space there and run the updater again. Nothing was changed.')

    n = {'added': 0, 'updated': 0, 'removed': 0, 'unchanged': 0}
    backup = os.path.join(target, 'lionels-updater-backup')

    # 3. Overwrite set: make these files match the zip.
    section('Mods, scripts and resource packs')
    installed = [e['rel'] for e in ow_list] if manifest is not None else get_files(overwrite)
    if manifest is not None:   # only the files missing or different, straight into the instance
        want = []
        for i, e in enumerate(ow_list):
            bar('Checking files', i / max(1, len(ow_list)), f'{i + 1} of {len(ow_list)}')
            dest = resolve_safe(target, e['rel'])
            if os.path.isfile(dest) and os.path.getsize(dest) == e['size'] and sha1(dest) == e['sha']:
                n['unchanged'] += 1
                continue
            want.append(dict(e, to=dest, new=not os.path.exists(dest)))
        clear_bar()
        bad = get_manifest_files(want)
        if bad:
            fail(f"{len(bad)} file(s) of the update could not be downloaded (first: {bad[0]['rel']}). The ones before were "
                 'updated;\nrun the updater again to finish. Check your internet connection.')
        for w in want:
            n['added' if w['new'] else 'updated'] += 1
            change('+' if w['new'] else '~', w['rel'])
    for i, rel in enumerate([] if manifest is not None else installed):
        bar('Checking files', i / max(1, len(installed)), f'{i + 1} of {len(installed)}')
        dest, src_file = resolve_safe(target, rel), os.path.join(overwrite, rel)
        if not os.path.exists(dest):
            copy_to(src_file, dest); n['added'] += 1; clear_bar(); change('+', rel)
        elif not same_file(src_file, dest):
            copy_to(src_file, dest); n['updated'] += 1; clear_bar(); change('~', rel)
        else:
            n['unchanged'] += 1
    clear_bar()

    # 4. Files an earlier update installed that are no longer part of it (an old version of a mod, for instance). Only
    #    with the update's files at hand: without them every listed file would look gone from the update.
    if have_files:
        keep = set(installed)
        for rel in read_list(record):
            old = resolve_safe(target, rel)
            if rel not in keep and rel not in optional_paths and os.path.isfile(old):
                os.remove(old); n['removed'] += 1; change('-', rel)
        write_text(record, ''.join(r + '\n' for r in installed))

    # 3b. Another version of a mod this update installs: two jars with one mod id stop the game. Any jar in mods/ this
    #     update did not install that declares a mod id one of its jars declares goes to the backup folder.
    shipped_ids, shipped_jars = {}, set()
    for j in ([resolve_safe(target, r) for r in installed if re.match(r'^mods/[^/]+\.jar$', r)] if manifest is not None
              else jars(os.path.join(overwrite, 'mods'))):
        shipped_jars.add(os.path.basename(j).lower())
        for i in mod_ids(j):
            shipped_ids[i] = os.path.basename(j)
    if shipped_ids:
        mine = jars(os.path.join(target, 'mods'))
        for k, j in enumerate(mine):
            bar('Looking for old versions of the same mods', k / max(1, len(mine)), f'{k + 1} of {len(mine)}')
            name = os.path.basename(j)
            clash = [i for i in mod_ids(j) if i in shipped_ids] if name.lower() not in shipped_jars else []
            if clash:
                move_to(j, os.path.join(backup, 'mods', name)); n['removed'] += 1; clear_bar()
                change('-', f'mods/{name}  (another version of {shipped_ids[clash[0]]}; kept in lionels-updater-backup)')
        clear_bar()

    # 5. Pack files this update removes. Moved to the backup folder, not erased; a line ending in / is a folder (a cache)
    #    and is deleted. A * in the last part matches any characters, in any case, as on Windows.
    expanded = []
    for r in read_list(os.path.join(src, 'delete.txt')):
        r = r.replace('\\', '/')
        if '*' not in r:
            expanded.append(r)
            continue
        folder = r[:r.rfind('/') + 1]
        parent = os.path.join(target, folder) if folder else target
        if os.path.isdir(parent):
            pattern = r[len(folder):].lower()
            expanded += [folder + e.name for e in sorted(os.scandir(parent), key=lambda e: e.name)
                         if e.is_file() and fnmatch.fnmatchcase(e.name.lower(), pattern)]
    for rel in expanded:
        victim = resolve_safe(target, rel)
        if rel.endswith('/'):
            if os.path.isdir(victim):
                shutil.rmtree(victim); n['removed'] += 1; change('-', f'{rel}  (folder)')
        elif os.path.isfile(victim):
            move_to(victim, os.path.join(backup, rel)); n['removed'] += 1; change('-', f'{rel}  (kept in lionels-updater-backup)')

    potato_mode(target, src, n)

    # 5c. Optional mods (optional.txt): asked every run, Enter keeps; the choice is kept per instance. First run: on if the
    #     player already has it, off if they switched it off themselves, else its default. On: downloaded (SHA-1 checked)
    #     or a .disabled copy renamed back, other copies to the backup. Off: renamed .jar.disabled. Nothing is deleted.
    if optional:
        section('Optional mods')
        choice_path = os.path.join(target, 'lionels-updater-optional.txt')
        saved = {}
        for l in read_list(choice_path):
            m = re.match(r'^\s*([\w.-]+)\s*=\s*(on|off)\s*$', l)
            if m:
                saved[m.group(1)] = m.group(2) == 'on'
        by_id, off_ids = {}, set()
        mods_dir = os.path.join(target, 'mods')
        for j in jars(mods_dir):
            for i in mod_ids(j):
                by_id.setdefault(i, []).append(j)
        for j in jars(mods_dir, '.jar.disabled'):
            off_ids.update(mod_ids(j))
        on = {}
        for m in optional:
            if m['id'] in saved:
                on[m['id']] = saved[m['id']]
            elif any(i in by_id for i in m['ids']):
                on[m['id']] = True
            elif any(i in off_ids for i in m['ids']):
                on[m['id']] = False
            else:
                on[m['id']] = m['default']
        own = dict(on)   # potato mode (5p): all off for this run, the player's own choices kept for when it is off
        if POTATO:
            on = {k: False for k in on}
            say('\nOptional mods: all off while potato mode is on.')
        while not POTATO:
            say('\nOptional mods (only on this PC; the server does not need them):')
            for k, m in enumerate(optional, 1):
                say(f"  {k}) [{'x' if on[m['id']] else ' '}] {m['name']}: {m['about']}")
            answer = env('LIONEL_UPDATER_OPTIONAL') or ask('Type numbers to switch them on or off (e.g. 1 3) and press Enter; Enter alone keeps these: ')
            answer = (answer or '').strip()
            if not answer or answer == 'keep':
                break
            for x in re.split(r'[\s,]+', answer):
                if x.isdigit() and 1 <= int(x) <= len(optional):
                    m = optional[int(x) - 1]
                    on[m['id']] = not on[m['id']]
                else:
                    say(f"  '{x}' is not one of the numbers above.", '33')
            if env('LIONEL_UPDATER_OPTIONAL'):
                break   # tests answer once
        for m in optional:
            if on[m['id']]:
                ours, complete = set(), True
                for rel, url, want in m['files']:
                    dest = resolve_safe(target, rel)
                    ours.add(dest)
                    if os.path.isfile(dest) and sha1(dest) == want:
                        continue
                    if os.path.isfile(dest + '.disabled') and sha1(dest + '.disabled') == want:
                        move_to(dest + '.disabled', dest); n['added'] += 1; change('+', f'{rel}  (switched back on)')
                        continue
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    part = dest + '.download'
                    if download(url, part, m['name']) and sha1(part) == want:
                        n['updated' if os.path.exists(dest) else 'added'] += 1
                        move_to(part, dest); change('+', rel)
                    else:
                        if os.path.exists(part):
                            os.remove(part)
                        complete = False
                        say(f"  {m['name']} could not be downloaded, or was not the expected file: not installed. Run the updater again later.", '33')
                if complete:
                    for i in m['ids']:
                        for j in by_id.get(i, []):
                            if j in ours or not os.path.isfile(j):
                                continue
                            move_to(j, os.path.join(backup, 'mods', os.path.basename(j))); n['removed'] += 1
                            change('-', f"mods/{os.path.basename(j)}  (another copy of {m['name']}; kept in lionels-updater-backup)")
            else:
                for i in m['ids']:
                    for j in by_id.get(i, []):
                        if os.path.isfile(j):
                            move_to(j, j + '.disabled'); n['removed'] += 1
                            change('-', f"mods/{os.path.basename(j)}  ({m['name']} switched off: renamed .jar.disabled)")
        keep = own if POTATO else on
        write_text(choice_path, ''.join(f"{m['id']}={'on' if keep[m['id']] else 'off'}\n" for m in optional))

    # 6. Defaults: only where the player has no file of their own.
    section('Settings')
    if manifest is not None:
        want = [dict(e, to=resolve_safe(target, e['rel'])) for e in im_list if not os.path.exists(resolve_safe(target, e['rel']))]
        bad = get_manifest_files(want)
        for w in want:
            if w not in bad:
                n['added'] += 1
                change('+', w['rel'])
        if bad:
            say(f'  {len(bad)} default file(s) could not be downloaded; the next run tries again.', '33')
    for rel in ([] if manifest is not None else get_files(if_missing)):
        dest = resolve_safe(target, rel)
        if not os.path.exists(dest):
            copy_to(os.path.join(if_missing, rel), dest); n['added'] += 1; change('+', rel)

    # 7. The Shooting Star font pack switched on: one entry added to options.txt's resource pack list, nothing else.
    options = os.path.join(target, 'options.txt')
    pack = 'file/lionel-shooting-star-fonts'
    if os.path.isfile(options) and os.path.isdir(os.path.join(target, 'resourcepacks', 'lionel-shooting-star-fonts')):
        text = read_text(options)
        line = re.search(r'(?m)^resourcePacks:\[(.*?)\](?=\r?$)', text)
        if line and f'"{pack}"' not in line.group():
            if not os.path.exists(options + '.bak-lionel'):
                shutil.copy2(options, options + '.bak-lionel')
            lst = line.group(1)
            save_text(options, text[:line.start()] + 'resourcePacks:[' + lst + (',' if lst else '') + f'"{pack}"]' + text[line.end():])
            change('~', 'options.txt: switched on the Shooting Star font pack (your other settings are untouched)')

    # 8. FancyMenu refuses to start beside WaterMedia 2 without the pack's dependency override in config/fml.toml.
    fml = os.path.join(target, 'config', 'fml.toml')
    mods_dir = os.path.join(target, 'mods')
    if os.path.isfile(fml) and any(fnmatch.fnmatch(os.path.basename(j), 'watermedia-2.*.jar') for j in jars(mods_dir)):
        text = read_text(fml)
        if not re.search(r'(?m)^\s*fancymenu\s*=', text):
            nl = '\r\n' if '\r\n' in text else '\n'
            override = '\tfancymenu = ["-watermedia"]'
            sec = re.search(r'(?m)^\[dependencyOverrides\][^\r\n]*\r?\n?', text)
            if not os.path.exists(fml + '.bak-lionel'):
                shutil.copy2(fml, fml + '.bak-lionel')
            if sec:
                text = text[:sec.start()] + sec.group().rstrip('\r\n') + nl + override + nl + text[sec.end():]
            else:
                text = text.rstrip('\r\n') + nl + '[dependencyOverrides]' + nl + override + nl
            save_text(fml, text)
            change('~', 'config/fml.toml: allowed FancyMenu to run beside WaterMedia 2 (one line added)')

    # 9. JEI's tooltip search indexed every item on each world join: off, once, only from the pack's default.
    jei = os.path.join(target, 'config', 'jei', 'jei-client.ini')
    if os.path.isfile(jei) and not os.path.exists(jei + '.bak-lionel'):
        text = read_text(jei)
        line = re.search(r'(?m)^(\s*tooltipSearchMode\s*=\s*)ENABLED(?=\r?$)', text)
        if line:
            shutil.copy2(jei, jei + '.bak-lionel')
            save_text(jei, text[:line.start()] + line.group(1) + 'DISABLED' + text[line.end():])
            change('~', "config/jei/jei-client.ini: tooltip search ($) switched off, so joining a world no longer freezes")

    # 10, 11, 11b, 11d to 11h: the one-line edits of update.ps1, same patterns, same markers.
    edit_once(target, 'config/fancymenu/options.txt', [
        (r"(?m)^(B:play_vanilla_menu_music = )'true';(?=\r?$)", "'false';"),
        (r"(?m)^(S:custom_window_title = )'';(?=\r?$)", "'ATM10: Lionels Additions';")],
        "the title screen has its own music now, so the game's menu music is off (two lines)")
    edit_once(target, 'config/crash_assistant/config.toml', [
        (r'(?ms)^(\[too_many_changes_warning\]\r?\n(?:[ \t]*#[^\n]*\n)*[ \t]*count = )5(?=\r?$)', '-1')],
        'the "too many changes" warning is off: this pack adds its mods on purpose (one line)')
    pong_mark = fml + '.bak-lionel-pong'
    if os.path.isfile(fml) and not os.path.exists(pong_mark) and any(
            fnmatch.fnmatch(os.path.basename(j), 'lionel-pong-*.jar') for j in jars(mods_dir)):
        text = read_text(fml)
        line = re.search(r'(?m)^(earlyWindowProvider\s*=\s*)"fmlearlywindow"', text)
        if line:
            shutil.copy2(fml, pong_mark)
            save_text(fml, text[:line.start()] + line.group(1) + '"lionelpong"' + text[line.end():])
            change('~', 'config/fml.toml: the loading screen plays Pong (earlyWindowProvider = "lionelpong")')
    edit_once(target, 'config/tacz-client.toml', [(r'(?m)^([ \t]*DisableInteractHudText = )false(?=\r?$)', 'true')],
              "TaCZ's \"[O] to interact\" text is off; the key still works (one line)")
    edit_once(target, 'config/notenoughanimations.json', [(r'("tweakElytraAnimation"\s*:\s*)true', 'false')],
              "Not Enough Animations' Elytra arm pose is off: it doubled the arms on a gun while gliding (one line)")
    edit_once(target, 'config/moreoverlays.toml', [
        (r'(?m)^([ \t]*search_tooltip = )true(?=\r?$)', 'false'), (r'(?m)^([ \t]*custom_search = )true(?=\r?$)', 'false')],
        "More Overlays' item search matches item names only, not whole tooltips (two lines)")
    edit_once(target, 'config/chloride-client.toml', [
        (r'(?m)^(\[fastBlocks\]\r?\n(?:[ \t]*#[^\n]*\n)*[ \t]*chests = )false(?=\r?$)', 'true')],
        "Chloride's Fast Chests are on: chests draw as plain models; lids no longer animate (one line)")
    edit_once(target, 'config/immediatelyfast.json', [(r'(?m)^([ \t]*"font_atlas_resizing": )true(?=,?\r?$)', 'false')],
              "ImmediatelyFast's font atlas resizing is off: on some graphics drivers it turned all text into black boxes")
    edit_once(target, 'config/almostunified/placeholders.json', [
        (r'(?m)^([ \t]*)"tin",(?=\r?\n)(?![\s\S]*"titanium")', '"tin",\n    "titanium",')],
        'Almost Unified merges the two titaniums (one line)')

    # 11c. lionel-turbo switches the player's file does not mention at all are appended with their comment line.
    turbo_rel = 'config/lionel-turbo.properties'
    shipped, mine_path = os.path.join(if_missing, turbo_rel), os.path.join(target, turbo_rel)
    if manifest is not None:
        t = [e for e in im_list if e['rel'] == turbo_rel.replace(os.sep, '/')]
        if t:
            get_manifest_files([dict(t[0], to=shipped)])
    if os.path.isfile(shipped) and os.path.isfile(mine_path):
        mine = read_text(mine_path)
        lines = read_text(shipped).replace('\r\n', '\n').split('\n')
        append, keys = '', []
        for i, l in enumerate(lines):
            m = re.match(r'^([A-Za-z0-9_]+)=', l)
            if not m or re.search(r'(?m)^[ \t]*' + re.escape(m.group(1)) + r'[ \t]*=', mine):
                continue
            comment = lines[i - 1] + '\n' if i > 0 and lines[i - 1].startswith('#') else ''
            append += '\n' + comment + l + '\n'
            keys.append(m.group(1))
        if keys:
            if mine and not mine.endswith('\n'):
                append = '\n' + append
            save_text(mine_path, mine + append)
            change('~', f"{turbo_rel}: new speed-up switches added: {', '.join(keys)} (your other switches unchanged)")

    setup_done = speed_setup(launcher, target, src)

    # 13. The instance's record: next run compares it with the version file online and skips the download when they match.
    if os.path.isfile(os.path.join(src, 'version.txt')):
        shutil.copyfile(os.path.join(src, 'version.txt'), os.path.join(STATE, 'version.txt'))
        shutil.copyfile(os.path.join(src, 'version.txt'), os.path.join(target, 'lionels-updater-version.txt'))

    say(f"\nDone. Added {n['added']}, updated {n['updated']}, removed {n['removed']}, already up to date {n['unchanged']}.", '32')
    if shutil.which('notify-send') and not env('LIONEL_UPDATER_NO_START'):
        subprocess.run(['notify-send', 'Advancement Made!', f"Lionel's ATM10, installed ({label})" if mode == 'fresh'
                        else f'Up to date: update {label}'], stderr=subprocess.DEVNULL)
    inst = os.path.dirname(target) if os.path.basename(target) in ('minecraft', '.minecraft') else target
    say('\nWhat to do now:', '36')
    say(f'  1. In {NAMES[launcher]}, click Play on "{os.path.basename(inst)}".')
    if not setup_done:
        say('     First set its speed settings: LAUNCH-ARGUMENTS.txt in the ATM10 folder has them.')
    if mode == 'fresh':
        say('     The first start of a new instance takes longer than later ones (5 minutes or more is normal).')
    say('  2. On the title screen, click "Join Lionel\'s Server" (or turn on Auto-join next to it to join on every start).')
    say('  3. Next time there is an update, just run this updater again.')
    return 0


def speed_setup(launcher, target, src):
    """12. Lionel's speed setup: Java 21.0.12.1 of the updater's own (Azul Zulu, the build the resolver patch is made
    for), his Java arguments with the patch, the memory preset. ATLauncher and Prism keep these in files this writes (with
    the launcher closed); the Modrinth app keeps them in its database, so its player is walked through three pastes."""
    section('Speed setup')
    # A Flatpak launcher only sees its own folder, so Java goes there; otherwise in the updater's data folder.
    fp = re.match(re.escape(FLATPAK) + r'/([^/]+)/', target + '/')
    tool_dir = os.path.join(FLATPAK, fp.group(1), 'data', 'lionels-updater') if fp else os.path.join(DATA, 'lionels-updater')
    os.makedirs(tool_dir, exist_ok=True)
    arch = {'x86_64': 'x64', 'amd64': 'x64', 'aarch64': 'aarch64', 'arm64': 'aarch64'}.get(platform.machine().lower())
    java_name = f'zulu21.52.203-ca-jre21.0.12.1-linux_{arch}'
    java_home = os.path.join(tool_dir, java_name)
    java_exe = os.path.join(java_home, 'bin', 'java')
    java_url = env('LIONEL_UPDATER_JAVA_URL') or (f'https://cdn.azul.com/zulu/bin/{java_name}.tar.gz' if arch else 'none')

    def java_ok():
        return os.access(java_exe, os.X_OK) and 'JAVA_VERSION="21.0.12.1"' in (
            read_text(os.path.join(java_home, 'release')) if os.path.isfile(os.path.join(java_home, 'release')) else '')

    if not java_ok() and java_url != 'none':
        say('\nDownloading Java 21.0.12.1 for the faster start (about 50 MB, once)...')
        tgz = os.path.join(tool_dir, 'java.tar.gz')
        if download(java_url, tgz, 'Java 21.0.12.1'):
            shutil.rmtree(java_home, ignore_errors=True)
            try:
                with tarfile.open(tgz) as t:
                    if hasattr(tarfile, 'data_filter'):
                        t.extractall(tool_dir, filter='data')
                    else:
                        t.extractall(tool_dir)
            except (tarfile.TarError, OSError) as e:
                say(f'  Could not unpack it ({e}).', '33')
            os.remove(tgz)
        if not java_ok():
            say('  Could not get it. The game still starts, about a minute slower; run the updater again later to retry.', '33')
    have_java = java_ok()
    patch_arg = ''
    patch_from = os.path.join(src, 'java', 'resolver-patch.jar')
    if have_java and os.path.isfile(patch_from):
        patch_to = os.path.join(tool_dir, 'resolver-patch.jar')
        if not os.path.isfile(patch_to) or not same_file(patch_from, patch_to):
            copy_to(patch_from, patch_to)
        if not re.search(r'\s', patch_to):   # launchers split the Java arguments at spaces
            patch_arg = f' --patch-module=java.base={patch_to}'

    # Memory preset, asked every run; Enter keeps the last choice (first time: the one that suits this PC).
    ram = ram_gb()
    mem_seen = os.path.join(STATE, 'memory.txt')
    mem, why = (16 if ram >= 30 else 12 if ram >= 20 else 8), 'suits this PC'
    if first_line(mem_seen) in ('8', '12', '16'):
        mem, why = int(first_line(mem_seen)), 'your last choice'
    if POTATO:
        mem, why = 8, 'potato mode'
    say(f'\nMemory for Minecraft: {mem} GB ({why}; this PC has {ram} GB of RAM).')
    pick = '' if POTATO else (env('LIONEL_UPDATER_MEMORY') or ask('  Press Enter to keep it, or type 8, 12 or 16 and press Enter: ') or '')
    pick = pick.strip().upper().rstrip('B').rstrip('G').strip()
    if pick in ('8', '12', '16'):
        mem = int(pick)
    elif pick:
        say(f"  '{pick}' is not 8, 12 or 16: keeping {mem} GB.", '33')
    if mem > ram - 6:
        say(f"  Warning: {mem} GB leaves the system less than 6 GB of this PC's {ram} GB. Pick a smaller preset if it slows down.", '33')
    if not POTATO:   # potato mode keeps the player's own preset for later
        write_text(mem_seen, f'{mem}\n')
    mem_mb = mem * 1024
    # 12 and 16 GB: Lionel's own line (generational ZGC). 8 GB: ZGC needs room to spare, so the G1 flags most packs use.
    gc = (' -XX:+UseZGC -XX:+ZGenerational' if mem >= 12 else
          ' -XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 -XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40'
          ' -XX:G1HeapRegionSize=8M -XX:G1ReservePercent=20 -XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4'
          ' -XX:InitiatingHeapOccupancyPercent=15 -XX:G1MixedGCLiveThresholdPercent=90 -XX:SurvivorRatio=32 -XX:MaxTenuringThreshold=1')
    # ATLauncher and Prism set -Xmx from their memory setting, so their line starts after it.
    arg_rest = (f'-XX:+UnlockExperimentalVMOptions{gc} -XX:+DisableExplicitGC -XX:+PerfDisableSharedMem'
                ' -XX:+UseFastUnorderedTimeStamps -Dfml.readTimeout=180 -Dfml.loginTimeout=180' + patch_arg +
                ' -XX:+UnlockDiagnosticVMOptions -XX:-BytecodeVerificationRemote')
    arg_line = f'-Xmx{mem}G {arg_rest}'
    java_note = (f'Java: {java_exe} (Java 21.0.12.1, which the patch needs).' if have_java else
                 "Java: the launcher's own (Java 21.0.12.1 could not be downloaded, so the resolver patch is left out: about a minute slower).")
    write_text(os.path.join(target, 'LAUNCH-ARGUMENTS.txt'), f"""Lionel's Additions: speed setup (fastest start, the same as Lionel's). Written by the updater; run it again to redo it.

ATLAUNCHER: the updater writes these into the instance itself (ATLauncher must be closed while it runs). By hand:
  Instances tab > this instance > Settings > Java/Minecraft:
    Maximum Memory: {mem_mb} MB
    Java Path: {java_home}
    Java Parameters: {arg_rest}

PRISM LAUNCHER: the updater writes these into the instance itself (Prism must be closed while it runs). By hand:
  this instance > Edit > Settings: tick Memory, Java installation and Java arguments:
    Maximum memory allocation: {mem_mb} MiB
    Java executable: {java_exe}
    JVM arguments: {arg_rest}

MODRINTH APP: open this instance's Settings, then "Java and memory":
  1. Switch "Custom memory allocation" on and type {mem_mb} in the box right of the slider.
  2. Switch "Custom Java installation" on and put this in its box: {java_exe}
  3. Switch "Custom Java arguments" on and replace the box's contents with this ONE line:

{arg_line}

Memory preset: {mem} GB ({mem_mb} MB) of this PC's {ram} GB; the updater asks every run (8, 12 or 16 GB).
{java_note}
-XX:-BytecodeVerificationRemote skips Java's re-check of mod code as it loads (25 to 40 s); a broken mod then crashes
less politely. To go back: turn the custom settings off; the launcher uses its own defaults again.
""")
    arg_seen = os.path.join(STATE, 'launch-args.txt')
    arg_key = f"{target} | {java_exe if have_java else ''} | {mem_mb} | {arg_line}"
    last_key = first_line(arg_seen)

    def closed(name):
        for _ in range(3):
            if not launcher_running(launcher):
                return True
            say(f'\n{name} is open. Close it completely, then press Enter here.', '33')
            if ask(f'  (It keeps its own copy of the instance settings and would write it back over the new ones.) ') is None:
                break
        if launcher_running(launcher):
            say(f'\n{name} stayed open, so its speed settings were not written. Run the updater again with it closed, or', '33')
            say('  set them by hand: LAUNCH-ARGUMENTS.txt in your ATM10 folder has the steps.', '33')
            return False
        return True

    done = False
    if launcher == 'ATLauncher':
        atl = os.path.join(target, 'instance.json')
        if not os.path.isfile(atl):
            say('\nThis folder has no instance.json, so it is not an ATLauncher instance: set up the speed settings by hand (LAUNCH-ARGUMENTS.txt in it).', '33')
        elif closed('ATLauncher'):
            text = read_text(atl)
            new = set_json_key(text, 'javaArguments', json_text(arg_rest))
            new = set_json_key(new, 'maximumMemory', str(mem_mb))
            if have_java:
                new = set_json_key(new, 'javaPath', json_text(java_home))
                new = set_json_key(new, 'useJavaProvidedByMinecraft', 'false')
            if new != text:
                if not os.path.exists(atl + '.bak-lionel'):
                    shutil.copy2(atl, atl + '.bak-lionel')
                save_text(atl, new)
                say("\nNEW LAUNCH ARGUMENTS written into ATLauncher's settings for this instance:", '36')
                say(f"  memory {mem_mb} MB; {f'Java 21.0.12.1 ({java_home}); ' if have_java else ''}Java arguments: {arg_rest}")
            done = True
    elif launcher == 'Prism':
        cfg = os.path.join(os.path.dirname(target), 'instance.cfg')
        if not os.path.isfile(cfg):
            say('\nNo instance.cfg beside this folder, so it is not a Prism instance: set up the speed settings by hand (LAUNCH-ARGUMENTS.txt in it).', '33')
        elif closed('Prism Launcher'):
            text = read_text(cfg)
            keys = {'OverrideMemory': 'true', 'MaxMemAlloc': str(mem_mb), 'OverrideJavaArgs': 'true', 'JvmArgs': arg_rest}
            if have_java:
                keys.update({'OverrideJava': 'true', 'OverrideJavaLocation': 'true', 'JavaPath': java_exe, 'AutomaticJava': 'false'})
            new = set_cfg_keys(text, keys)
            if new != text:
                if not os.path.exists(cfg + '.bak-lionel'):
                    shutil.copy2(cfg, cfg + '.bak-lionel')
                save_text(cfg, new)
                say("\nNEW LAUNCH ARGUMENTS written into Prism's settings for this instance:", '36')
                say(f"  memory {mem_mb} MB; {f'Java 21.0.12.1 ({java_exe}); ' if have_java else ''}Java arguments: {arg_rest}")
            done = True
    else:
        if last_key != arg_key:
            steps = [('Open this ATM10 instance\'s Settings in the Modrinth app and click "Java and memory" on the left.', None),
                     ('Memory: switch "Custom memory allocation" on, click the number box at the right end of the slider, select all (Ctrl+A) and paste (Ctrl+V):', str(mem_mb))]
            if have_java:
                steps.append(('Java: switch "Custom Java installation" on, click in its box, select all (Ctrl+A) and paste (Ctrl+V):', java_exe))
            steps.append(('Arguments: switch "Custom Java arguments" on, click in its box, select all (Ctrl+A) and paste (Ctrl+V):', arg_line))
            say(f'\nSPEED SETTINGS for the Modrinth app, {len(steps)} steps.', '36')
            read_steps(steps, 'modrinth-java-and-memory.png', src)
            say('\n  The same steps are in LAUNCH-ARGUMENTS.txt in your ATM10 folder.')
        done = True
    if done:
        write_text(arg_seen, arg_key + '\n')
    return done


if __name__ == '__main__':
    sys.exit(main())
