#!/usr/bin/env python3
# Runs update_linux.py (through update-lionels-additions.sh) against fake packs in a fake home folder: never the real
# one. On Linux (WSL works): python3 test_linux.py
import hashlib, os, shutil, subprocess, sys, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
root = tempfile.mkdtemp(prefix='lionels-updater-test.')
home = os.path.join(root, 'home')
passed = failed = 0


def check(what, ok):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f'FAIL: {what}')


def write(path, text, crlf=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='') as f:
        f.write(text.replace('\n', '\r\n') if crlf else text)


def read(path):
    with open(path, newline='') as f:
        return f.read()


def jar(path, mod_id, extra=''):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('META-INF/neoforge.mods.toml', f'modLoader="javafml"\n[[mods]]\nmodId="{mod_id}"\nversion="1"\n')
        z.writestr('x.txt', extra or path)


def make_instance(path, atl=False):
    write(f'{path}/config/bcc-common.toml', '[general]\n\tmodpackName = "All the Mods 10"\n\tmodpackVersion = "8.1"\n')
    jar(f'{path}/mods/oldcc-1.0.jar', 'computercraft', 'old')
    jar(f'{path}/mods/voxy-0.1.jar', 'voxy')
    jar(f'{path}/mods/watermedia-2.1.0.jar', 'watermedia')
    jar(f'{path}/mods/ShoulderSurfing-old.jar', 'shouldersurfing')
    write(f'{path}/options.txt', 'version:3955\nresourcePacks:["vanilla","fabric"]\nkey_key.jump:key.keyboard.space\n', crlf=True)
    write(f'{path}/config/fml.toml', 'earlyWindowProvider = "fmlearlywindow"\n[dependencyOverrides]\n')
    write(f'{path}/config/jei/jei-client.ini', '[search]\n  tooltipSearchMode = ENABLED\n')
    write(f'{path}/config/keep-me.toml', 'mine = true\n')
    write(f'{path}/kubejs/startup_scripts/update_checker.js', 'old')
    write(f'{path}/mods/mcef-cache/a.bin', 'cache')
    write(f'{path}/config/lionel-turbo.properties', '# a\nfirst=true\n')
    if atl:
        write(f'{path}/instance.json', '{\n  "launcher": {\n    "name": "ATM10",\n    "maximumMemory": 4096\n  },\n  "libraries": []\n}\n')


def make_zip(path, version, files, extra=None):
    stage = path + '.stage'
    shutil.rmtree(stage, ignore_errors=True)
    for rel, content in files.items():
        if isinstance(content, tuple):
            jar(f'{stage}/{rel}', *content)
        else:
            write(f'{stage}/{rel}', content)
    write(f'{stage}/version.txt', version + '\n')
    for rel, content in (extra or {}).items():
        write(f'{stage}/{rel}', content)
    with zipfile.ZipFile(path, 'w') as z:
        for d, _, names in os.walk(stage):
            for n in names:
                full = os.path.join(d, n)
                z.write(full, './' + os.path.relpath(full, stage))
    shutil.rmtree(stage)


# The optional mod's download (a file: address) and its SHA-1
opt_jar = os.path.join(root, 'web', 'ShoulderSurfing-new.jar')
jar(opt_jar, 'shouldersurfing', 'new')
opt_sha = hashlib.sha1(open(opt_jar, 'rb').read()).hexdigest()
OPTIONAL = ('# optional\nshouldersurfing|Shoulder Surfing|camera|on|shouldersurfing|'
            f'mods/ShoulderSurfing-new.jar>file://{opt_jar}>{opt_sha}\n')
DELETE = 'kubejs/startup_scripts/update_checker.js\nmods/voxy-*.jar\nmods/mcef-cache/\n'
BASE = {
    'overwrite/mods/cc-tweaked-2.0.jar': ('computercraft', 'new'),
    'overwrite/mods/lionel-pong-1.0.jar': ('lionelpong',),
    'overwrite/mods/gone-later.jar': ('gonelater',),
    'overwrite/kubejs/server_scripts/lionel/boss_balance.js': 'rules',
    'overwrite/resourcepacks/lionel-shooting-star-fonts/pack.mcmeta': '{}',
    'if-missing/config/keep-me.toml': 'shipped = true\n',
    'if-missing/config/new-default.toml': 'x = 1\n',
    'if-missing/config/lionel-turbo.properties': '# a\nfirst=true\n# b switch\nsecond=true\n',
    'delete.txt': DELETE,
    'optional.txt': OPTIONAL,
    'java/resolver-patch.jar': 'patch',
}
web = os.path.join(root, 'web')
zip1 = os.path.join(web, 'update1.zip')
make_zip(zip1, '2026-10-20 10:00', BASE)
write(os.path.join(web, 'version.txt'), '2026-10-20 10:00\n')


def run(answers='', extra_env=None, args=()):
    e = {k: v for k, v in os.environ.items() if not k.startswith(('LIONEL_', 'XDG_'))}
    e.update({'HOME': home, 'TMPDIR': os.path.join(root, 'tmp'), 'LIONEL_UPDATER_LOGIC_URL': 'file://' + HERE,
              'LIONEL_UPDATER_ZIP_URL': 'file://' + zip1, 'LIONEL_UPDATER_VERSION_URL': 'file://' + os.path.join(web, 'version.txt'),
              'LIONEL_UPDATER_FULL_URL': 'none', 'LIONEL_UPDATER_JAVA_URL': 'none', 'LIONEL_UPDATER_NO_CLIPBOARD': '1',
              'LIONEL_UPDATER_NO_START': '1', 'LIONEL_UPDATER_NO_PAUSE': '1', 'LIONEL_UPDATER_ATL_OPEN': '0',
              'LIONEL_UPDATER_RAM_GB': '32', 'LIONEL_UPDATER_FILES_URL': 'none', 'DISPLAY': '', 'WAYLAND_DISPLAY': ''})
    e.update(extra_env or {})
    os.makedirs(e['TMPDIR'], exist_ok=True)
    p = subprocess.run(['bash', os.path.join(HERE, 'update-lionels-additions.sh'), *args], input=answers, text=True,
                       capture_output=True, env=e, timeout=120)
    return p.returncode, p.stdout + p.stderr


atl = os.path.join(home, '.local/share/atlauncher/instances/ATM10')
make_instance(atl, atl=True)
prism = os.path.join(home, '.local/share/PrismLauncher/instances/ATM10/.minecraft')
make_instance(prism)
write(os.path.join(os.path.dirname(prism), 'instance.cfg'), '[General]\nInstanceType=OneSix\nname=ATM10\n')

# 1. ATLauncher: launcher 1, update 1, the only instance found (Enter), optional mods kept, memory kept
rc, out = run('1\n1\n\n\n\n')
check('ATLauncher run exits 0\n' + out, rc == 0)
check('instance found by its launcher folder', f'1) {atl}' in out)
check('new jar added', os.path.isfile(f'{atl}/mods/cc-tweaked-2.0.jar'))
check('older version of the same mod id moved to the backup', not os.path.exists(f'{atl}/mods/oldcc-1.0.jar')
      and os.path.isfile(f'{atl}/lionels-updater-backup/mods/oldcc-1.0.jar'))
check('delete.txt file moved to the backup', os.path.isfile(f'{atl}/lionels-updater-backup/kubejs/startup_scripts/update_checker.js'))
check('delete.txt * matched', os.path.isfile(f'{atl}/lionels-updater-backup/mods/voxy-0.1.jar'))
check('delete.txt folder deleted', not os.path.exists(f'{atl}/mods/mcef-cache'))
check('if-missing does not overwrite', read(f'{atl}/config/keep-me.toml') == 'mine = true\n')
check('if-missing adds', os.path.isfile(f'{atl}/config/new-default.toml'))
opts = read(f'{atl}/options.txt')
check('font pack added, CRLF and keybinds kept', 'resourcePacks:["vanilla","fabric","file/lionel-shooting-star-fonts"]\r\n' in opts
      and 'key_key.jump:key.keyboard.space\r\n' in opts and os.path.isfile(f'{atl}/options.txt.bak-lionel'))
fml = read(f'{atl}/config/fml.toml')
check('watermedia override added', '[dependencyOverrides]\n\tfancymenu = ["-watermedia"]\n' in fml)
check('pong switched on', 'earlyWindowProvider = "lionelpong"' in fml and os.path.isfile(f'{atl}/config/fml.toml.bak-lionel-pong'))
check('JEI tooltip search off', 'tooltipSearchMode = DISABLED' in read(f'{atl}/config/jei/jei-client.ini'))
check('turbo switch appended', read(f'{atl}/config/lionel-turbo.properties') == '# a\nfirst=true\n\n# b switch\nsecond=true\n')
check('optional mod downloaded, old copy to the backup', os.path.isfile(f'{atl}/mods/ShoulderSurfing-new.jar')
      and os.path.isfile(f'{atl}/lionels-updater-backup/mods/ShoulderSurfing-old.jar'))
check('optional choice saved', read(f'{atl}/lionels-updater-optional.txt') == 'shouldersurfing=on\n')
check('installed list written', 'mods/gone-later.jar\n' in read(f'{atl}/lionels-updater-installed.txt'))
check('version recorded', read(f'{atl}/lionels-updater-version.txt') == '2026-10-20 10:00\n')
ij = read(f'{atl}/instance.json')
check('instance.json memory and arguments', '"maximumMemory": 16384' in ij and '"javaArguments": "-XX:+UnlockExperimentalVMOptions -XX:+UseZGC' in ij
      and '"libraries": []' in ij and os.path.isfile(f'{atl}/instance.json.bak-lionel'))
check('LAUNCH-ARGUMENTS.txt written', '-Xmx16G' in read(f'{atl}/LAUNCH-ARGUMENTS.txt'))
check('no temporary files left', not os.listdir(os.path.join(root, 'tmp')))

# 2. Nothing new: potato mode never answered (2026-10-22), then that question instead of "nothing to do"; once
# answered, no download, Enter closes. Potato mode is offered in the menu now that an ATM10 is known.
rc, out = run('1\n\n\n\n\n')
check('latest, potato never answered: the update runs for its question\n' + out, rc == 0 and 'One new question first' in out
      and '3) Potato mode' in out)
write(os.path.join(home, '.config/lionels-updater/potato-decided.txt'), 'off\n')
rc, out = run('1\n\n\n')
check('already latest is noticed\n' + out, rc == 0 and 'You already have the latest update' in out and 'Downloading the latest' not in out)

# 2b. ATLauncher open (2026-10-22): settings already right, left alone; changed, closed by the updater, written, reopened
rc, out = run('\nr\n' + '\n' * 8, {'LIONEL_UPDATER_LAUNCHER': 'ATLauncher', 'LIONEL_UPDATER_MODE': 'update', 'LIONEL_UPDATER_ATL_OPEN': '1'})
check('ATLauncher open, settings right: not closed, nothing asked\n' + out, rc == 0 and 'Done.' in out and 'Close it completely' not in out
      and 'stayed open' not in out)
write(f'{atl}/instance.json', read(f'{atl}/instance.json').replace('"maximumMemory": 16384', '"maximumMemory": 4096'))
rc, out = run('\nr\n' + '\n' * 8, {'LIONEL_UPDATER_LAUNCHER': 'ATLauncher', 'LIONEL_UPDATER_MODE': 'update', 'LIONEL_UPDATER_ATL_OPEN': 'closable'})
check('ATLauncher open, settings changed: closed, written, reopened\n' + out, rc == 0 and 'closed: it opens again' in out
      and 'opening again' in out and '"maximumMemory": 16384' in read(f'{atl}/instance.json'))

# 3. A newer update without gone-later.jar: removed through the installed list; optional mod switched off
files2 = dict(BASE)
del files2['overwrite/mods/gone-later.jar']
make_zip(zip1, '2026-10-21 10:00', files2)
write(os.path.join(web, 'version.txt'), '2026-10-21 10:00\n')
rc, out = run('\n\n\n', {'LIONEL_UPDATER_OPTIONAL': '1'})
check('second update exits 0\n' + out, rc == 0)
check('jar no longer shipped is removed', not os.path.exists(f'{atl}/mods/gone-later.jar'))
check('optional mod switched off is renamed', os.path.isfile(f'{atl}/mods/ShoulderSurfing-new.jar.disabled')
      and not os.path.exists(f'{atl}/mods/ShoulderSurfing-new.jar'))

# 4. Prism: the cfg beside .minecraft gets the settings; memory 8 typed
rc, out = run('3\n1\n\n8\n',{'LIONEL_UPDATER_OPTIONAL': 'keep'})
check('Prism run exits 0\n' + out, rc == 0)
cfg = read(os.path.join(os.path.dirname(prism), 'instance.cfg'))
check('instance.cfg written', 'MaxMemAlloc=8192' in cfg and 'OverrideJavaArgs=true' in cfg and 'JvmArgs=-XX:+UnlockExperimentalVMOptions -XX:+UseG1GC' in cfg
      and cfg.startswith('[General]\n'))

# 5. A faulty update (a protected path) changes nothing
bad = os.path.join(web, 'bad.zip')
make_zip(bad, '2026-10-22 10:00', {'overwrite/options.txt': 'evil', 'overwrite/mods/new-thing.jar': ('newthing',)})
rc, out = run('1\n\n\n', {'LIONEL_UPDATER_ZIP_URL': 'file://' + bad, 'LIONEL_UPDATER_LAUNCHER': 'ATLauncher'})
write(os.path.join(web, 'version.txt'), '2026-10-22 10:00\n')
rc, out = run('\n', {'LIONEL_UPDATER_ZIP_URL': 'file://' + bad, 'LIONEL_UPDATER_LAUNCHER': 'ATLauncher', 'LIONEL_UPDATER_MODE': 'update'})
check('protected path refused\n' + out, rc == 1 and 'Refusing to touch a player settings file' in out)
check('nothing changed by the faulty update', not os.path.exists(f'{atl}/mods/new-thing.jar') and 'evil' not in read(f'{atl}/options.txt'))

# 6. The game running from the instance (a process called java whose folder is the instance) stops the update
java = os.path.join(root, 'bin', 'java')
os.makedirs(os.path.dirname(java), exist_ok=True)
shutil.copy('/bin/sleep', java)
game = subprocess.Popen([java, '30'], cwd=atl)
try:
    rc, out = run('\n', {'LIONEL_UPDATER_LAUNCHER': 'ATLauncher', 'LIONEL_UPDATER_MODE': 'update', 'LIONEL_UPDATER_ZIP_URL': 'file://' + zip1})
    check('running game noticed\n' + out, rc == 1 and 'Minecraft looks like it is running' in out)
finally:
    game.kill()

# 7. A zip given on the command line, no download
make_zip(zip1, '2026-10-23 10:00', BASE)
rc, out = run('\n\n', {'LIONEL_UPDATER_LAUNCHER': 'ATLauncher', 'LIONEL_UPDATER_ZIP_URL': 'file:///nonexistent'}, args=[zip1])
check('given zip used\n' + out, rc == 0 and read(f'{atl}/lionels-updater-version.txt') == '2026-10-23 10:00\n'
      and os.path.isfile(f'{atl}/mods/gone-later.jar') and os.path.isfile(zip1))

# 8. Potato mode (5p) with the real potato.txt: on, then off again with everything back but the player's own change
potato_zip = os.path.join(web, 'potato.zip')
make_zip(potato_zip, '2026-10-24 10:00', BASE, {'potato.txt': read(os.path.join(HERE, 'potato.txt'))})
jar(f'{atl}/mods/iris-neoforge-1.8.jar', 'iris')
write(f'{atl}/resourcepacks/lionel-lowres.zip', 'pack')
po_opts = ('version:3955\nkey_key.jump:key.keyboard.space\nrenderDistance:12\ngraphicsMode:1\n'
           'resourcePacks:["vanilla","file/FreshAnimations_v1.9.2.zip","file/lionel-shooting-star-fonts"]\n')
write(f'{atl}/options.txt', po_opts, crlf=True)
po_chl = '[nametags]\n  entities = true\n[culling]\n  entities = false\n  entityLimit = 60\n'
write(f'{atl}/config/chloride-client.toml', po_chl)
po_env = {'LIONEL_UPDATER_LAUNCHER': 'ATLauncher', 'LIONEL_UPDATER_ZIP_URL': 'file:///nonexistent', 'LIONEL_UPDATER_POTATO': 'Y'}
rc, out = run('\n\n\n\n', po_env, args=[potato_zip])
o = read(f'{atl}/options.txt')
check('potato on exits 0\n' + out, rc == 0 and 'Potato mode is on' in out)
check('potato on: Iris renamed .jar.disabled', os.path.isfile(f'{atl}/mods/iris-neoforge-1.8.jar.disabled'))
check('potato on: settings set, CRLF and keybind kept', 'renderDistance:3\r\n' in o and 'graphicsMode:0\r\n' in o
      and 'key_key.jump:key.keyboard.space\r\n' in o)
check('potato on: pack list', 'resourcePacks:["vanilla","file/lionel-shooting-star-fonts","file/lionel-lowres.zip"]\r\n' in o)
check('potato on: Chloride, each entities key in its own section', read(f'{atl}/config/chloride-client.toml')
      == po_chl.replace('[nametags]\n  entities = true', '[nametags]\n  entities = false')
      .replace('entities = false\n  entityLimit = 60', 'entities = true\n  entityLimit = 25'))
check('potato on: optional mod off, choice kept, 8 GB', os.path.isfile(f'{atl}/mods/ShoulderSurfing-new.jar.disabled')
      and read(f'{atl}/lionels-updater-optional.txt') == 'shouldersurfing=off\n' and '-Xmx8G' in read(f'{atl}/LAUNCH-ARGUMENTS.txt'))
# potato.txt changed after it was applied (2026-10-22): a value potato mode wrote follows the new rule, a rule gone puts
# the player's own back (gamma here, as the sky)
rec = read(f'{atl}/lionels-updater-potato.txt')
write(f'{atl}/lionels-updater-potato.txt', rec.replace('graphicsMode\t1\t0', 'graphicsMode\t1\t5') + 'set\toptions.txt\t-\tgamma\t0.5\t1.0\n')
write(f'{atl}/options.txt', o.replace('graphicsMode:0', 'graphicsMode:5') + 'gamma:1.0\r\n')
rc, out = run('\n\n\n\n', po_env, args=[potato_zip])
rec = read(f'{atl}/lionels-updater-potato.txt')
check('potato rules changed since: new value where potato\'s was, a dropped rule\'s setting back\n' + out, rc == 0
      and read(f'{atl}/options.txt') == o + 'gamma:0.5\r\n' and 'graphicsMode\t1\t0' in rec and 'gamma' not in rec)
write(f'{atl}/options.txt', o.replace('renderDistance:3', 'renderDistance:6'))   # the player's own change meanwhile
po_env['LIONEL_UPDATER_POTATO'] = 'N'
rc, out = run('\n\n\n\n', po_env, args=[potato_zip])
check('potato off exits 0\n' + out, rc == 0 and 'everything it changed is back' in out)
check('potato off: options back but the player\'s render distance', read(f'{atl}/options.txt')
      == po_opts.replace('renderDistance:12', 'renderDistance:6').replace('\n', '\r\n'))
check('potato off: Chloride back, Iris back', read(f'{atl}/config/chloride-client.toml') == po_chl
      and os.path.isfile(f'{atl}/mods/iris-neoforge-1.8.jar'))

# 9. Per-file updates (R2): r2_publish.py's layout in a folder; only the changed jar is downloaded, no zip
r2_stage, r2 = os.path.join(root, 'r2stage'), os.path.join(root, 'r2')
files9 = dict(BASE)
files9['overwrite/mods/cc-tweaked-3.0.jar'] = ('computercraft', 'newer')
del files9['overwrite/mods/cc-tweaked-2.0.jar']
zip9 = os.path.join(web, 'update9.zip')
make_zip(zip9, '2026-10-25 10:00', files9)
with zipfile.ZipFile(zip9) as z:
    z.extractall(r2_stage)
subprocess.run([sys.executable, os.path.join(HERE, 'r2_publish.py'), r2_stage, os.path.join(r2_stage, 'version.txt'), '--to', r2],
               check=True, capture_output=True)
r2_env = {'LIONEL_UPDATER_LAUNCHER': 'ATLauncher', 'LIONEL_UPDATER_MODE': 'update', 'LIONEL_UPDATER_FILES_URL': 'file://' + r2,
          'LIONEL_UPDATER_ZIP_URL': 'file:///nonexistent'}
rc, out = run('\n\n\n\n', r2_env)
check('per-file run exits 0\n' + out, rc == 0 and 'Downloading 1 file(s)' in out and 'about 800 MB' not in out)
check('per-file: the new jar in, the old one out, version recorded', os.path.isfile(f'{atl}/mods/cc-tweaked-3.0.jar')
      and not os.path.exists(f'{atl}/mods/cc-tweaked-2.0.jar') and read(f'{atl}/lionels-updater-version.txt') == '2026-10-25 10:00\n')
write(f'{atl}/mods/cc-tweaked-3.0.jar', 'damaged')
rc, out = run('r\n\n\n\n', r2_env)
check('per-file: R again repairs a damaged file only\n' + out, rc == 0 and 'Downloading 1 file(s)' in out
      and zipfile.is_zipfile(f'{atl}/mods/cc-tweaked-3.0.jar'))

# 10. Fresh install into ATLauncher (2026-10-22): potato asked before the download; the instance written by the
# updater from atlauncher-instance.json (no import), then updated; the sign-in steps at the end.
mrpack = os.path.join(web, 'full.mrpack')
with zipfile.ZipFile(mrpack, 'w') as z:
    z.writestr('modrinth.index.json', '{"formatVersion":1,"game":"minecraft","versionId":"t","name":"x","files":[],'
                                      '"dependencies":{"minecraft":"1.21.1","neoforge":"21.1.249"}}')
    z.writestr('overrides/config/bcc-common.toml', 'modpackName = "All the Mods 10"\nmodpackVersion = "8.1"\n')
    z.writestr('overrides/mods/base-mod.jar', 'base')
rc, out = run('\n' * 12, {'LIONEL_UPDATER_LAUNCHER': 'ATLauncher', 'LIONEL_UPDATER_MODE': 'fresh', 'LIONEL_UPDATER_POTATO': 'N',
                          'LIONEL_UPDATER_FULL_URL': 'file://' + mrpack, 'LIONEL_UPDATER_ZIP_URL': 'file://' + zip9})
made = os.path.join(home, '.local/share/atlauncher/instances/LionelsATM10')
check('fresh ATLauncher exits 0\n' + out, rc == 0 and 'Now import it' not in out)
check('fresh ATLauncher: instance written and updated', os.path.isfile(f'{made}/mods/base-mod.jar')
      and os.path.isfile(f'{made}/mods/cc-tweaked-3.0.jar') and '"name": "Lionel\'s ATM10"' in read(f'{made}/instance.json')
      and '__UUID__' not in read(f'{made}/instance.json'))
check('fresh: potato asked before the download, sign-in steps at the end', 0 <= out.find('Potato mode, for weak')
      < out.find('Downloading the whole pack') and out.find('Login with Microsoft') > out.find('What to do now'))

shutil.rmtree(root)
print(f'{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
