#!/usr/bin/env python3
"""i3status JSON bridge and GTK calendar. stdout belongs exclusively to i3bar."""
import argparse
import calendar
import configparser
import datetime as dt
import fcntl
import json
import locale
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading


def warn(message):
    print(f'i3-calendar: {message}', file=sys.stderr, flush=True)


def read_config(path):
    config = configparser.ConfigParser(interpolation=None)
    config.read_dict({
        'calendar': {'locale': 'system', 'close_on_outside_click': 'off',
                     'block_name': 'tztime', 'block_instance': 'local'},
        'colors': {'background': '#000000', 'text': '#FFFFFF', 'muted': '#888888',
                   'border': '#83CAFA', 'button_background': '#222222',
                   'button_hover': '#4C4C4C', 'today_background': '#51A2DA',
                   'today_text': '#FFFFFF'},
    })
    if path.exists():
        with path.open() as stream:
            config.read_file(stream)
    config.getboolean('calendar', 'close_on_outside_click')
    for key, value in config['colors'].items():
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            raise ValueError(f'Invalid color {key}: {value}; expected #RRGGBB')
    return config


def set_locale(requested):
    for name in ([requested] if requested != 'system' else []) + ['', 'C']:
        try:
            locale.setlocale(locale.LC_TIME, name)
            return
        except locale.Error:
            warn(f'Locale {name or "system"} is unavailable; trying a fallback.')


def first_weekday():
    # glibc locale metadata is also what GTK uses for its calendar convention.
    try:
        result = subprocess.run(['locale', '-k', 'LC_TIME'], capture_output=True,
                                text=True, check=True,
                                env={**os.environ, 'LC_ALL': locale.setlocale(locale.LC_TIME)})
        fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        origin = dt.datetime.strptime(fields['week-1stday'].strip('"'), '%Y%m%d').date()
        return (origin.weekday() + int(fields['first_weekday']) - 1) % 7
    except (OSError, subprocess.SubprocessError, KeyError, ValueError):
        return calendar.MONDAY


class OutsideClicks:
    """Observe button presses without grabbing or replaying anyone's input."""
    def __init__(self, callback, idle_add):
        from Xlib import X, display
        from Xlib.ext import record
        from Xlib.protocol import rq
        self.control = display.Display()
        self.data = display.Display()
        self.closed = False
        if not self.control.has_extension('RECORD'):
            self.data.close()
            self.control.close()
            raise RuntimeError('The X server does not support RECORD')
        self.context = self.control.record_create_context(
            0, [record.AllClients], [{'core_requests': (0, 0), 'core_replies': (0, 0),
                                     'ext_requests': (0, 0, 0, 0), 'ext_replies': (0, 0, 0, 0),
                                     'delivered_events': (0, 0),
                                     'device_events': (X.ButtonPress, X.ButtonPress),
                                     'errors': (0, 0), 'client_started': False,
                                     'client_died': False}])
        self.control.sync()

        def receive(reply):
            if self.closed or reply.category != record.FromServer or reply.client_swapped:
                return
            data = reply.data
            while data:
                event, data = rq.EventField(None).parse_binary_value(data, self.data.display, None, None)
                # Scrolling is navigation, not a click outside.
                if event.type == X.ButtonPress and event.detail in (1, 2, 3):
                    # RECORD device ButtonPress has no guaranteed root coordinates.
                    pointer = self.control.screen().root.query_pointer()
                    idle_add(callback, pointer.root_x, pointer.root_y, event.detail)

        def run():
            try:
                self.data.record_enable_context(self.context, receive)
            except Exception as exc:
                if not self.closed:
                    warn(f'Outside-click monitoring stopped: {exc}')
            finally:
                self.data.close()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def close(self):
        self.closed = True
        self.control.record_disable_context(self.context)
        self.control.flush()
        self.thread.join(timeout=1)
        self.control.record_free_context(self.context)
        self.control.close()


class App:
    def __init__(self, config, args):
        import gi
        gi.require_version('Gtk', '3.0')
        gi.require_version('Gdk', '3.0')
        from gi.repository import Gdk, GLib, Gtk
        self.Gdk, self.GLib, self.Gtk = Gdk, GLib, Gtk
        ok, _ = Gtk.init_check()
        if not ok or not os.environ.get('DISPLAY'):
            raise RuntimeError('An i3/X11 graphical session and DISPLAY are required')
        self.config = config
        self.window = None
        self.observer = None
        self.stopping = False
        self.date_rect = None
        self.lock = None
        self.firstweekday = first_weekday()
        self.today = dt.date.today()
        self.child = None
        self.exit_code = 0
        colors = config['colors']
        css = '''
        #i3-calendar { background: %(background)s; color: %(text)s;
                       border: 1px solid %(border)s; }
        #i3-calendar label { color: %(text)s; }
        #i3-calendar button { background-image: none; background-color: %(button_background)s;
          color: %(text)s; border: 0; box-shadow: none; padding: 5px; min-height: 20px; }
        #i3-calendar button:hover { background-color: %(button_hover)s; }
        #i3-calendar .weekday, #i3-calendar .adjacent-month { color: %(muted)s; }
        #i3-calendar .today { background-color: %(today_background)s; color: %(today_text)s;
                              border-radius: 4px; }
        ''' % dict(colors)
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        if config.getboolean('calendar', 'close_on_outside_click'):
            self.observer = OutsideClicks(self.outside_click, GLib.idle_add)
        command = ['i3status']
        if args.i3status_config:
            command += ['-c', str(Path(args.i3status_config).expanduser())]
        try:
            self.child = subprocess.Popen(command, stdout=subprocess.PIPE, text=True, bufsize=1)
        except Exception:
            if self.observer:
                self.observer.close()
            raise
        threading.Thread(target=self.output, daemon=True).start()
        threading.Thread(target=self.input, daemon=True).start()
        GLib.timeout_add_seconds(1, self.tick)
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, self.stop)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, self.refresh)

    def output(self):
        try:
            header = json.loads(self.child.stdout.readline())
            if header.get('version') != 1:
                raise ValueError('Set output_format = "i3bar" in the general section of the i3status configuration')
            header.update(click_events=True, stop_signal=0, cont_signal=0)
            print(json.dumps(header), flush=True)
            for line in self.child.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
        except (ValueError, BrokenPipeError) as exc:
            warn(str(exc))
            self.exit_code = 1
        finally:
            self.GLib.idle_add(self.stop)

    def input(self):
        try:
            for line in sys.stdin:
                text = line.strip().lstrip(',').strip()
                if not text or text in ('[', ']'):
                    continue
                try:
                    event = json.loads(text)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    self.GLib.idle_add(self.click, event)
        finally:
            self.GLib.idle_add(self.stop)

    def click(self, event):
        settings = self.config['calendar']
        if (event.get('button') != 1 or event.get('name') != settings['block_name']
                or event.get('instance', '') != settings['block_instance']):
            return False
        if self.window:
            self.close_window()
        else:
            self.open_window(event)
        return False

    def open_window(self, event):
        # All wrappers for this user share one popup lock.
        runtime = Path(os.environ.get('XDG_RUNTIME_DIR',
                       os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache')))) / 'i3-calendar'
        runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = (runtime / 'popup.lock').open('w')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            return
        self.lock = lock
        Gtk, Gdk = self.Gtk, self.Gdk
        x, y = int(event.get('x', 0)), int(event.get('y', 0))
        left = x - int(event.get('relative_x', 0))
        top = y - int(event.get('relative_y', 0))
        self.date_rect = (left, top, max(1, int(event.get('width', 1))),
                          max(1, int(event.get('height', 1))))
        self.today = dt.date.today()
        self.year, self.month = self.today.year, self.today.month
        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window = window
        window.set_wmclass('i3-calendar', 'I3Calendar')
        window.set_name('i3-calendar')
        window.set_title('i3-calendar')
        window.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        window.set_decorated(False)
        window.set_resizable(False)
        window.set_skip_taskbar_hint(True)
        window.set_skip_pager_hint(True)
        window.set_keep_above(True)
        window.connect('delete-event', lambda *_: self.close_window() or True)
        window.connect('key-press-event', self.keypress)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(10)
        window.add(box)
        navigation = Gtk.Box(spacing=5)
        box.pack_start(navigation, False, False, 0)
        self.nav = []
        for label, delta in [('«', -12), ('‹', -1), ('›', 1), ('»', 12)]:
            button = Gtk.Button(label=label)
            button.connect('clicked', lambda _, step=delta: self.navigate(step))
            navigation.pack_start(button, True, True, 0)
            self.nav.append((button, delta))
        self.heading = Gtk.Label()
        box.pack_start(self.heading, False, False, 0)
        self.grid = Gtk.Grid(column_spacing=4, row_spacing=4)
        box.pack_start(self.grid, True, True, 0)
        # A locale-formatted date avoids a hard-coded language in the Today control.
        today_button = Gtk.Button(label='● ' + self.today.strftime('%x'))
        today_button.set_tooltip_text(self.today.strftime('%A, %d %B %Y'))
        today_button.connect('clicked', self.go_today)
        self.today_button = today_button
        box.pack_start(today_button, False, False, 0)
        self.render()
        monitor = Gdk.Display.get_default().get_monitor_at_point(x, y)
        bounds = monitor.get_workarea()

        def position(*_):
            width, height = window.get_size()
            px = max(bounds.x, min(left + self.date_rect[2] - width,
                                   bounds.x + bounds.width - width))
            above = top - height - 4
            py = above if above >= bounds.y else top + self.date_rect[3] + 4
            py = max(bounds.y, min(py, bounds.y + bounds.height - height))
            window.move(px, py)
        window.connect('size-allocate', position)
        window.show_all()
        position()
        window.present()

    def render(self):
        for child in self.grid.get_children():
            self.grid.remove(child)
        self.heading.set_text(dt.date(self.year, self.month, 1).strftime('%B %Y'))
        for column in range(7):
            label = self.Gtk.Label(label=calendar.day_abbr[(self.firstweekday + column) % 7])
            label.get_style_context().add_class('weekday')
            self.grid.attach(label, column, 0, 1, 1)
        first_weekday, days_in_month = calendar.monthrange(self.year, self.month)
        leading_days = (first_weekday - self.firstweekday) % 7
        previous_year = self.year if self.month > 1 else self.year - 1
        previous_month = self.month - 1 if self.month > 1 else 12
        previous_days = calendar.monthrange(previous_year, previous_month)[1]
        for row in range(6):
            for column in range(7):
                day = row * 7 + column - leading_days + 1
                current_month = 1 <= day <= days_in_month
                display_day = (previous_days + day if day < 1 else
                               day - days_in_month if day > days_in_month else day)
                label = self.Gtk.Label(label=str(display_day))
                label.set_size_request(34, 28)
                if not current_month:
                    label.get_style_context().add_class('adjacent-month')
                elif dt.date(self.year, self.month, day) == self.today:
                    label.get_style_context().add_class('today')
                self.grid.attach(label, column, row + 1, 1, 1)
        index = (self.year - 1) * 12 + self.month - 1
        for button, delta in self.nav:
            button.set_sensitive(0 <= index + delta < 9999 * 12)
        self.grid.show_all()

    def navigate(self, delta):
        index = (self.year - 1) * 12 + self.month - 1 + delta
        if 0 <= index < 9999 * 12:
            self.year, month = divmod(index, 12)
            self.year += 1
            self.month = month + 1
            self.render()

    def go_today(self, *_):
        self.today = dt.date.today()
        self.year, self.month = self.today.year, self.today.month
        self.render()

    def tick(self):
        today = dt.date.today()
        if self.window and today != self.today:
            self.today = today
            self.today_button.set_label('● ' + today.strftime('%x'))
            self.today_button.set_tooltip_text(today.strftime('%A, %d %B %Y'))
            self.render()
        return True

    def keypress(self, _, event):
        if event.keyval == self.Gdk.KEY_Escape:
            self.close_window()
            return True
        return False

    @staticmethod
    def inside(x, y, rect):
        left, top, width, height = rect
        return left <= x < left + width and top <= y < top + height

    def outside_click(self, x, y, button):
        if not self.window:
            return False
        if button == 1 and self.inside(x, y, self.date_rect):
            # i3bar owns toggling the date: never close then reopen the same click.
            return False
        position, size = self.window.get_position(), self.window.get_size()
        if not self.inside(x, y, (*position, *size)):
            self.close_window()
        return False

    def close_window(self):
        if self.window:
            window, self.window = self.window, None
            window.destroy()
        if self.lock:
            self.lock.close()
            self.lock = None

    def refresh(self):
        if self.child and self.child.poll() is None:
            self.child.send_signal(signal.SIGUSR1)
        return True

    def stop(self):
        if self.stopping:
            return False
        self.stopping = True
        self.close_window()
        if self.observer:
            self.observer.close()
        if self.child:
            if self.child.poll() is None:
                self.child.terminate()
                try:
                    self.child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.child.kill()
                    self.child.wait()
            elif self.child.returncode:
                self.exit_code = 1
        self.Gtk.main_quit()
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
    parser.add_argument('--config', type=Path, default=default / 'i3-calendar/calendar.conf')
    parser.add_argument('--i3status-config')
    args = parser.parse_args()
    try:
        config = read_config(args.config.expanduser())
        set_locale(config['calendar']['locale'])
        app = App(config, args)
        app.Gtk.main()
        return app.exit_code
    except (ImportError, OSError, ValueError, RuntimeError, configparser.Error) as exc:
        warn(str(exc))
        return 1


if __name__ == '__main__':
    sys.exit(main())
