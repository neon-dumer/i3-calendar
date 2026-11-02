#!/usr/bin/env python3
"""User-local installation with reversible, narrowly scoped config edits."""
import argparse
import configparser
import datetime
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

from calendar_app import read_config


RULE = 'for_window [class="^I3Calendar$"] floating enable, border pixel 0'
MARKER = '# i3-calendar: managed window rule'


def locations():
    home = Path.home()
    return {
        'app': Path(os.environ.get('XDG_DATA_HOME', home / '.local/share')) / 'i3-calendar',
        'config': Path(os.environ.get('XDG_CONFIG_HOME', home / '.config')) / 'i3-calendar',
        'state': Path(os.environ.get('XDG_STATE_HOME', home / '.local/state')) / 'i3-calendar',
        'launcher': home / '.local/bin/i3-calendar',
    }


def atomic_write(path, text, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode if mode is not None else
                 (path.stat().st_mode & 0o777 if path.exists() else 0o600))
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def config_path(explicit, candidates, label):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f'{label}: file not found: {path}')
        return path
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise ValueError(f'Could not find {label}. Specify its path explicitly or use --manual.')


def blocks(text):
    """Recognize top-level brace blocks, ignoring quoted strings and comments."""
    stack, result = [], []
    quoted = escaped = comment = False
    line_start = 0
    for index, char in enumerate(text):
        if char == '\n':
            line_start = index + 1
            comment = False
        if comment:
            continue
        if escaped:
            escaped = False
            continue
        if quoted and char == '\\':
            escaped = True
            continue
        if char == '"':
            quoted = not quoted
            continue
        if quoted:
            continue
        if char == '#':
            comment = True
            continue
        if char == '{':
            stack.append((text[line_start:index].strip(), index))
        elif char == '}':
            if not stack:
                raise ValueError('Unbalanced braces in the configuration')
            name, opening = stack.pop()
            if not stack:
                result.append((name, opening + 1, index))
    if stack or quoted:
        raise ValueError('Unterminated block or string in the configuration')
    return result


def dependencies(calendar_config):
    if sys.platform != 'linux' or sys.version_info < (3, 9):
        raise ValueError('Linux and Python 3.9 or newer are required.')
    session = os.environ.get('XDG_SESSION_TYPE', '').lower()
    if session and session != 'x11':
        raise ValueError(f'Session {session!r} is not supported. Log into an i3 (X11) session. '
                         'Installation under Wayland, GNOME Wayland, or from a TTY is not allowed.')
    if os.environ.get('WAYLAND_DISPLAY') or os.environ.get('SWAYSOCK'):
        raise ValueError('A Wayland/Sway session was detected. An i3 session under X11 is required; '
                         'a DISPLAY provided by XWayland is not sufficient.')
    if not os.environ.get('DISPLAY'):
        raise ValueError('DISPLAY is not set. Run the installer from a terminal in an i3/X11 session.')
    missing = [name for name in ('i3', 'i3bar', 'i3-msg', 'i3status') if not shutil.which(name)]
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        gi.require_version('Gdk', '3.0')
        gi.require_version('GdkX11', '3.0')
        from gi.repository import Gdk, GdkX11, Gtk
    except (ImportError, ValueError):
        missing.append('GTK 3 / GdkX11 / PyGObject')
    if missing:
        raise ValueError('Missing dependencies: ' + ', '.join(missing) + '\n'
                         'Fedora: sudo dnf install i3 i3status python3-gobject gtk3\n'
                         'Debian/Ubuntu: sudo apt install i3-wm i3status python3-gi gir1.2-gtk-3.0')
    initialized, _ = Gtk.init_check()
    connection = Gdk.Display.get_default()
    if not initialized or not isinstance(connection, GdkX11.X11Display):
        raise ValueError('GTK 3 cannot connect to X11. Check DISPLAY, '
                         'session access, and GDK_BACKEND; run without sudo.')
    wm = GdkX11.X11Screen.get_window_manager_name(Gdk.Screen.get_default())
    if wm.lower() != 'i3':
        raise ValueError(f'The active window manager is {wm!r}; i3 is required. '
                         'Having the i3 package installed is not sufficient. '
                         'Log out of the current session and select i3 on the login screen.')
    try:
        response = subprocess.run(['i3-msg', '-t', 'get_version'], capture_output=True,
                                  text=True, timeout=5, check=True)
        version = json.loads(response.stdout)
        if (not isinstance(version, dict) or not isinstance(version.get('major'), int)
                or version['major'] < 4 or 'sway' in version.get('human_readable', '').lower()):
            raise ValueError('Unsupported IPC response: i3 version 4 or newer is required.')
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        raise ValueError(f'Could not verify access to i3 over IPC: {exc}. '
                         'Check I3SOCK and run the script from the current i3 session.') from exc
    if read_config(calendar_config).getboolean('calendar', 'close_on_outside_click'):
        try:
            from Xlib import display
        except ImportError:
            raise ValueError('Outside-click monitoring requires python-xlib. Fedora: sudo dnf install '
                             'python3-xlib; Debian/Ubuntu: sudo apt install python3-xlib') from None
        try:
            connection = display.Display()
            try:
                if not connection.has_extension('RECORD'):
                    raise ValueError('The X server does not support RECORD')
            finally:
                connection.close()
        except Exception as exc:
            raise ValueError(f'X11 RECORD check failed: {exc}') from exc


def edit(path, old, new):
    return {'path': str(path), 'before': old, 'after': new}


def make_edits(args, paths):
    home = Path.home()
    config_home = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config'))
    i3 = config_path(args.i3_config, [config_home / 'i3/config', home / '.i3/config'], 'i3 configuration')
    text = i3.read_text()
    bars = [(start, end) for name, start, end in blocks(text) if name == 'bar']
    if args.bar is not None:
        selected = []
        for number, (start, end) in enumerate(bars, 1):
            ids = re.findall(r'^\s*id\s+([^\s#]+)', text[start:end], re.M)
            if args.bar == str(number) or args.bar in [value.strip('"') for value in ids]:
                selected.append((start, end))
    else:
        selected = bars
    if len(selected) != 1:
        raise ValueError('The bar is ambiguous or was not found. Specify --bar with its ID or number '
                         '(starting at 1). For included files, point --i3-config to the file containing the bar block; '
                         'use --manual for custom configurations.')
    start, end = selected[0]
    commands = list(re.finditer(r'^[ \t]*status_command[ \t]+([^\n]+)', text[start:end], re.M))
    if len(commands) != 1:
        raise ValueError('Expected one status_command line in the bar block. Use --manual.')
    match = commands[0]
    original = match.group(0)
    tokens = shlex.split(match.group(1), comments=True)
    if tokens and tokens[0] == 'exec':
        tokens = tokens[1:]
    status_arg = None
    if not tokens or Path(tokens[0]).name != 'i3status':
        raise ValueError('status_command is not a plain i3status command. Use --manual; '
                         'an existing wrapper will not be replaced automatically.')
    if len(tokens) == 3 and tokens[1] in ('-c', '--config'):
        status_arg = tokens[2]
        if '$' in status_arg or '`' in status_arg:
            raise ValueError('The i3status path contains variables. Use --manual.')
        if not Path(status_arg).expanduser().is_absolute():
            raise ValueError('A relative path in status_command is ambiguous. '
                             'Set an absolute path in the configuration or use --manual.')
    elif len(tokens) != 1:
        raise ValueError('Unsupported i3status arguments. Use --manual.')
    status = config_path(args.i3status_config or status_arg,
                         [config_home / 'i3status/config', home / '.i3status.conf',
                          Path('/etc/i3status.conf')], 'i3status configuration')
    if status == i3:
        raise ValueError('i3 and i3status must use different configuration files.')
    if not os.access(status, os.W_OK) or not os.access(status.parent, os.W_OK):
        raise ValueError(f'Configuration {status} is not writable. Copy it to '
                         '~/.config/i3status/config and specify --i3status-config.')
    status_text = status.read_text()
    general = [(a, b) for name, a, b in blocks(status_text) if name == 'general']
    if len(general) != 1:
        raise ValueError('Expected one general block in i3status. Use --manual.')
    a, b = general[0]
    formats = list(re.finditer(r'^[ \t]*output_format\s*=\s*[^\n]+', status_text[a:b], re.M))
    if len(formats) > 1:
        raise ValueError('Multiple output_format entries in general; fix the configuration manually.')
    result = []
    if formats:
        before = formats[0].group(0)
        # Only replace the value; preserve inline comments.
        value = re.search(r'(output_format\s*=\s*)("[^"]*"|[\w-]+)', before)
        if not value:
            raise ValueError('Could not parse output_format.')
        after = before[:value.start(2)] + '"i3bar"' + before[value.end(2):]
        if before != after:
            result.append(edit(status, before, after))
    else:
        # Include a unique existing anchor so insertion and removal are reversible.
        anchor = status_text[:a].splitlines(keepends=True)[-1]
        result.append(edit(status, anchor, anchor + '\n    output_format = "i3bar" # i3-calendar'))
    command = ' '.join(shlex.quote(str(value)) for value in
                       [paths['launcher'], '--config', paths['config'] / 'calendar.conf',
                        '--i3status-config', status])
    indent = original[:len(original) - len(original.lstrip())]
    replacement = edit(i3, original, indent + 'status_command ' + command)
    replacement['offset'] = start + match.start()
    result.append(replacement)
    if RULE not in text:
        # The window rule must be outside bar, so append it with an exact marker.
        suffix = '\n' + MARKER + '\n' + RULE + '\n'
        result.append(edit(i3, '', suffix))
    return result


def apply_edits(edits):
    originals, updated = {}, {}
    for entry in edits:
        path = Path(entry['path'])
        if path not in originals:
            originals[path] = path.read_text()
            updated[path] = originals[path]
        before, after = entry['before'], entry['after']
        if not before:
            updated[path] += after
        elif 'offset' in entry:
            offset = entry['offset']
            if updated[path][offset:offset + len(before)] != before:
                raise ValueError(f'Configuration {path} changed during preparation.')
            updated[path] = updated[path][:offset] + after + updated[path][offset + len(before):]
        elif updated[path].count(before) == 1:
            updated[path] = updated[path].replace(before, after, 1)
        else:
            raise ValueError(f'Ambiguous line in {path}; use --manual.')
    return originals, updated


def install(args, paths):
    source = Path(args.source).resolve()
    calendar_config = paths['config'] / 'calendar.conf'
    dependencies(calendar_config if calendar_config.exists() else source / 'config/calendar.conf')
    manifest_path = paths['state'] / 'install.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    if manifest:
        if any((args.i3_config, args.i3status_config, args.bar, args.manual)):
            raise ValueError('Updates use the saved paths. To change the integration, '
                             'run uninstall.sh first.')
        for entry in manifest['edits']:
            path = Path(entry['path'])
            if not path.exists() or path.read_text().count(entry['after']) != 1:
                raise ValueError(f'The installed integration has been modified: {path}. '
                                 'Restore it first or run uninstall.sh.')
        edits, originals, updated = [], {}, {}
    else:
        if paths['app'].exists() or paths['launcher'].exists():
            raise ValueError('The application or launcher path already exists without an installation journal; '
                             'existing files will not be overwritten.')
        edits = [] if args.manual else make_edits(args, paths)
        originals, updated = apply_edits(edits)
        manifest = {'version': 1, 'edits': edits, 'backups': {},
                    'app': str(paths['app']), 'launcher': str(paths['launcher'])}
    # Check every destination before creating even the installation journal.
    destinations = [paths['state'] / 'install.json', paths['config'] / 'calendar.conf',
                    paths['launcher'], paths['app'] / 'calendar_app.py',
                    paths['app'] / 'manage.py', *updated]
    for target in destinations:
        if not target.is_absolute():
            raise ValueError(f'The path must be absolute (check XDG variables): {target}')
        if target.exists() and not target.is_file():
            raise ValueError(f'Expected a file, but the path is occupied by another object: {target}')
        parent = target.parent
        while not parent.exists():
            parent = parent.parent
        if not parent.is_dir() or not os.access(parent, os.W_OK | os.X_OK):
            raise ValueError(f'No write access to {parent}. Run without sudo '
                             'and check permissions on user directories.')
    if args.check:
        print('Preflight passed: i3/X11, IPC, dependencies, settings, and installation paths are available. '
              'No files were changed.')
        return
    paths['state'].mkdir(parents=True, exist_ok=True)
    if not manifest_path.exists():
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        for number, (path, text) in enumerate(originals.items()):
            backup = paths['state'] / f'{stamp}-{number}.bak'
            atomic_write(backup, text)
            manifest['backups'][str(path)] = str(backup)
        # Write recovery information before any modification of user configs.
        atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    paths['app'].mkdir(parents=True, exist_ok=True)
    for filename in ('calendar_app.py', 'manage.py'):
        atomic_write(paths['app'] / filename, (source / 'src' / filename).read_text(), 0o644)
    if not calendar_config.exists():
        atomic_write(calendar_config, (source / 'config/calendar.conf').read_text())
    launcher = '#!/bin/sh\nexec python3 ' + shlex.quote(str(paths['app'] / 'calendar_app.py')) + ' "$@"\n'
    atomic_write(paths['launcher'], launcher, 0o755)
    try:
        for path, text in updated.items():
            atomic_write(path, text)
    except OSError:
        for path, text in originals.items():
            atomic_write(path, text)
        raise
    print('Calendar installed. User settings were preserved.')
    print(f'Configuration: {calendar_config}')
    if args.manual:
        print('Set output_format = "i3bar" in the i3status general section.')
        print('Replace status_command in the target bar with:')
        print('    status_command ' + shlex.quote(str(paths['launcher']))
              + ' --i3status-config /absolute/path/to/i3status/config')
        print('Add this outside the bar block: ' + RULE)
    print('Apply the configuration manually: i3-msg reload')
    print('If status_command did not restart: i3-msg restart')


def uninstall(args, paths):
    manifest_path = paths['state'] / 'install.json'
    if not manifest_path.exists():
        print('No installation journal was found; no files were changed.')
        return
    manifest = json.loads(manifest_path.read_text())
    changed, conflicts = {}, []
    for entry in reversed(manifest['edits']):
        path = Path(entry['path'])
        if not path.exists():
            continue
        text = changed.get(path, path.read_text())
        if text.count(entry['after']) == 1:
            changed[path] = text.replace(entry['after'], entry['before'], 1)
        elif (entry['after'] not in text
              and (not entry['before'] or entry['before'] in text)
              and not (not entry['before'] and (MARKER in text or RULE in text))
              and not ('status_command' in entry['after'] and manifest['launcher'] in text)):
            continue  # Already reverted by the user or a previous interrupted run.
        else:
            conflicts.append(str(path))
    if conflicts:
        raise ValueError('The integration was modified manually: ' + ', '.join(sorted(set(conflicts)))
                         + f'. Uninstallation stopped without changes. Review {manifest_path} '
                         'and restore the before or after string; then retry uninstallation.')
    for path, text in changed.items():
        atomic_write(path, text)
    launcher, app = Path(manifest['launcher']), Path(manifest['app'])
    launcher.unlink(missing_ok=True)
    for filename in ('calendar_app.py', 'manage.py'):
        (app / filename).unlink(missing_ok=True)
    # Only remove our generated bytecode, never recursively delete arbitrary user files.
    cache = app / '__pycache__'
    if cache.is_dir():
        for pattern in ('calendar_app.*.pyc', 'manage.*.pyc'):
            for path in cache.glob(pattern):
                path.unlink()
        if not any(cache.iterdir()):
            cache.rmdir()
    if app.exists() and not any(app.iterdir()):
        app.rmdir()
    if args.purge:
        (paths['config'] / 'calendar.conf').unlink(missing_ok=True)
        if paths['config'].exists() and not any(paths['config'].iterdir()):
            paths['config'].rmdir()
    # Keep backups and the completed journal available for manual recovery.
    manifest_path.rename(paths['state'] / ('uninstalled-' +
                         datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json'))
    print('Calendar removed; unrelated settings were preserved. Backups: ' + str(paths['state']))
    print('Apply the configuration manually: i3-msg reload (or i3-msg restart if needed).')
    if not args.purge:
        print('Calendar settings were kept in ' + str(paths['config']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    setup = sub.add_parser('install')
    setup.add_argument('--source', required=True)
    setup.add_argument('--i3-config')
    setup.add_argument('--i3status-config')
    setup.add_argument('--bar', help='bar ID or number, starting at 1')
    setup.add_argument('--manual', action='store_true', help='install files without changing configurations')
    setup.add_argument('--check', action='store_true', help='check only, without installing or writing files')
    remove = sub.add_parser('uninstall')
    remove.add_argument('--purge', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Run as a regular user without sudo.')
    try:
        paths = locations()
        if args.action == 'install':
            install(args, paths)
        else:
            uninstall(args, paths)
        return 0
    except (OSError, ValueError, configparser.Error) as exc:
        print(f'i3-calendar: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
