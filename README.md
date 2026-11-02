> [!NOTE]
> This project was developed with the assistance of artificial intelligence (AI).

<div align="center">

# i3-calendar

**A popup calendar for your i3status date block.**

Browse months and years without leaving your workspace.<br>
Keep your existing status bar, configuration, and workflow.

**Linux · i3 / X11 · Python 3.9+ · GTK 3**

[Quick start](#quick-start) · [Configuration](#configuration) · [Uninstall](#uninstall-and-rollback) · [Troubleshooting](#troubleshooting)

</div>

---

## Overview

i3-calendar wraps **i3status** and adds a calendar that opens when you left-click the date in **i3bar**. It preserves the existing status blocks and their formatting, so you can keep your volume, battery, network, and other indicators.

Use it to check dates, browse upcoming months, or look back at a previous year directly from your desktop panel.

### Features

- **Click to toggle:** open and close the calendar using the date block.
- **Month and year navigation:** separate controls for each, plus a return-to-today button.
- **Readable month view:** today is highlighted; adjacent-month dates are dimmed in a stable six-week grid.
- **Localized dates:** month names, weekdays, date formatting, and the first day of the week follow your selected locale.
- **Configurable appearance:** independent colors for text, backgrounds, buttons, borders, and today.
- **Optional outside-click closing:** close the calendar without swallowing the click in the other application.
- **User-local installation:** configuration backups, recorded edits, and removal that preserves unrelated settings.

> [!IMPORTANT]
> This project requires an active **i3 session under X11**. GNOME, Sway, Wayland, and installation from a TTY are not supported. Having i3 installed or a `DISPLAY` supplied by XWayland is not sufficient.

## Contents

- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Usage](#usage)
- [Configuration](#configuration)
- [Installation options](#installation-options)
- [Updates](#updates)
- [Uninstall and rollback](#uninstall-and-rollback)
- [Troubleshooting](#troubleshooting)
- [Limitations and behavior](#limitations-and-behavior)
- [Project layout](#project-layout)
- [Contributing](#contributing)
- [License](#license)

## Requirements

| Component | Requirement |
| --- | --- |
| Operating system | Linux |
| Desktop session | Active i3 4+ session under X11, with working IPC access |
| Status bar | `i3bar` and `i3status` |
| Runtime | Python 3.9 or newer |
| GUI | GTK 3, PyGObject, and GdkX11 |
| Date block | An existing i3status date block; defaults to `tztime local` |
| Optional | `python-xlib` and X11 RECORD for outside-click closing |

<details>
<summary><strong>Install dependencies on Fedora</strong></summary>

```sh
sudo dnf install python3 i3 i3status python3-gobject gtk3

# Optional: required for close_on_outside_click = on
sudo dnf install python3-xlib
```

</details>

<details>
<summary><strong>Install dependencies on Debian / Ubuntu</strong></summary>

```sh
sudo apt install python3 i3-wm i3status python3-gi gir1.2-gtk-3.0

# Optional: required for close_on_outside_click = on
sudo apt install python3-xlib
```

</details>

The installer checks dependencies but does not install system packages. Use your distribution's Python interpreter with access to its PyGObject packages.

## Quick start

Clone or download this repository, open a terminal in its root directory, and run these commands **from your i3 session, without sudo**.

### 1. Check your environment

```sh
./install.sh --check
```

This checks source syntax, dependencies, the X11 connection, the actual window manager, i3 IPC, configuration compatibility, and installation paths. It does not install anything or write files. If outside-click closing is enabled, it also checks python-xlib and RECORD.

### 2. Install

```sh
./install.sh
```

The installer backs up the affected configurations, changes the selected bar's `status_command`, adds a floating-window rule, and enables i3bar JSON output in i3status. Other status blocks and settings are preserved.

### 3. Apply the configuration

```sh
i3-msg reload
```

If the bar has not restarted its status command:

```sh
i3-msg restart
```

Left-click the date to open the calendar.

> [!NOTE]
> Installation never reloads or restarts i3 automatically. The example files in `config/` are minimal references, **not replacements for your complete desktop configuration**.

## Usage

| Action | Result |
| --- | --- |
| Left-click the date | Open the current month; click again to close |
| `‹` / `›` | Previous / next month |
| `«` / `»` | Previous / next year |
| `●` button with today's date | Return to the current month |
| Escape while the calendar has focus | Close the window |
| Click outside | Close only when `close_on_outside_click = on` |

The calendar opens near the clicked date, within the corresponding monitor's work area. For a bottom bar, it appears above the panel. Every new opening starts at the current month.

## Configuration

Edit `~/.config/i3-calendar/calendar.conf`, or `$XDG_CONFIG_HOME/i3-calendar/calendar.conf` if you use a custom XDG configuration directory.

### Calendar settings

```ini
[calendar]
locale = system
close_on_outside_click = off
block_name = tztime
block_instance = local
```

| Option | Default | Description |
| --- | --- | --- |
| `locale` | `system` | System locale or an installed locale such as `en_US.UTF-8` |
| `close_on_outside_click` | `off` | Close on an outside left, middle, or right mouse click |
| `block_name` | `tztime` | Target block's `name` in the i3status JSON output |
| `block_instance` | `local` | Target block's `instance` in the i3status JSON output |

List available locales with `locale -a`. If the requested locale is unavailable, the calendar reports a warning and tries the system locale, then `C`. If first-weekday metadata is unavailable, it uses Monday.

Outside-click closing requires the optional dependencies. The click still reaches the application under the pointer. Scrolling, pointer movement, and focus loss do not close the calendar.

### Colors

```ini
[colors]
background = #000000
text = #FFFFFF
muted = #888888
border = #83CAFA
button_background = #222222
button_hover = #4C4C4C
today_background = #51A2DA
today_text = #FFFFFF
```

All colors use `#RRGGBB`. `muted` controls weekday headings and adjacent-month dates. The default palette uses a black background, white text, and blue accents. It is independent of subsequent changes to your i3 theme.

After editing settings, run `./install.sh --check` to validate them, then `i3-msg restart` to restart the wrapper with the new configuration.

## Installation options

### Custom paths and multiple bars

```sh
./install.sh --i3-config ~/.config/i3/config \
  --i3status-config ~/.config/i3status/config \
  --bar 1
```

| Option | Purpose |
| --- | --- |
| `--check` | Validate without installing or writing files |
| `--i3-config PATH` | Select the i3 configuration file containing the target bar |
| `--i3status-config PATH` | Select the i3status configuration file |
| `--bar ID_OR_NUMBER` | Select a bar by ID or its position in the file, starting at 1 |
| `--manual` | Install application files without editing desktop configurations |

For a bar defined in an included file, point `--i3-config` to that file. Complex shell commands, existing wrappers, variables, and arbitrary include structures are not automatically rewritten. Ambiguous configurations stop installation before configuration edits; use manual integration instead.

If you currently use `/etc/i3status.conf`, copy it into your user configuration directory and pass that copy with `--i3status-config`.

### Installed files

| Purpose | Default location | Override |
| --- | --- | --- |
| Application | `~/.local/share/i3-calendar/` | `$XDG_DATA_HOME/i3-calendar/` |
| Launcher | `~/.local/bin/i3-calendar` | Fixed user-local path |
| Settings | `~/.config/i3-calendar/calendar.conf` | `$XDG_CONFIG_HOME/i3-calendar/calendar.conf` |
| Backups and installation journal | `~/.local/state/i3-calendar/` | `$XDG_STATE_HOME/i3-calendar/` |

The automatic integration uses an absolute launcher path, so adding `~/.local/bin` to `PATH` is optional. Keep the same XDG environment when updating or uninstalling.

### Manual integration

```sh
./install.sh --manual
```

Session and dependency checks still apply. Then make these changes yourself:

**In the existing i3status `general` block:**

```text
output_format = "i3bar"
```

**In the target i3 `bar` block:**

```text
status_command ~/.local/bin/i3-calendar --i3status-config ~/.config/i3status/config
```

**Outside the i3 `bar` block:**

```text
for_window [class="^I3Calendar$"] floating enable, border pixel 0
```

Adjust the paths to match your setup. The wrapper also accepts `--config /path/to/calendar.conf`. If `--i3status-config` is omitted, i3status uses its standard configuration search.

If your status configuration has no date block, add the following, avoiding duplicate entries:

```text
order += "tztime local"

tztime local {
    format = "%d.%m.%Y %H:%M"
}
```

Apply the configuration as described in [Quick start](#quick-start).

## Updates

Obtain the updated repository files, then run:

```sh
./install.sh --check
./install.sh
i3-msg restart
```

Updates preserve `calendar.conf` and reuse the paths recorded during installation. Do not repeat `--bar`, `--i3-config`, `--i3status-config`, or `--manual` when updating. To change the integration paths or mode, uninstall first, then install again with the desired options.

## Uninstall and rollback

### Restore the previous status command

```sh
./uninstall.sh
i3-msg reload
```

If the old wrapper is still running, use `i3-msg restart`.

Uninstallation removes the application and reverses recorded configuration edits, including the previous status command, while preserving unrelated user changes. Calendar settings are kept for future use.

To remove calendar settings as well, use this **instead of** the normal uninstall command:

```sh
./uninstall.sh --purge
```

Backups and completed journals remain available even with `--purge`. Unrecognized files in the application directory are not deleted.

### Uninstall without the repository

```sh
python3 "${XDG_DATA_HOME:-$HOME/.local/share}/i3-calendar/manage.py" uninstall
```

Append `--purge` to remove settings as well. An active i3 session is not required for uninstallation.

### Recover from configuration conflicts

If a managed line was edited manually, uninstallation may stop without changes rather than overwrite it. Review `install.json` in the state directory: each edit records its target `path`, `before` text, and `after` text. Restore the affected entry to one of those recorded states, then retry uninstallation.

Original configuration backups are stored alongside the journal. Use them for comparison and selective recovery; restoring an entire backup can discard changes made after installation.

> [!IMPORTANT]
> With manual integration, restore your original `status_command` and remove the added window rule yourself before uninstalling. Manually applied configuration edits are not recorded in the journal.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Unsupported session or window manager | Log into i3 under X11. Installing the i3 package while running GNOME or Wayland does not change the active session. |
| GTK cannot connect to X11 | Run from a terminal inside your desktop session, without sudo. Check `DISPLAY`, `GDK_BACKEND`, and access to the X server. |
| i3 IPC check fails | Check `I3SOCK` and confirm `i3-msg -t get_version` works in the current session. |
| Missing GTK / PyGObject | Install the distribution packages listed under Requirements and use a Python interpreter that can import them. |
| `status_command process exited unexpectedly` | Run the wrapper directly as shown below and read its stderr diagnostics. Check `output_format = "i3bar"`. |
| Clicking the date does nothing | Confirm the bar uses the wrapper, and that `block_name` / `block_instance` match the date block. Restart i3 after changing the configuration. |
| Outside clicks do not close the calendar | Enable `close_on_outside_click`, install python-xlib, check RECORD with `./install.sh --check`, and restart the wrapper. |
| Unexpected language or first weekday | Check `locale -a` and the configured locale. Unavailable locales trigger a fallback. |
| Multiple bars or an existing status wrapper | Select `--bar`, or use manual integration for a custom command. |
| Uninstall reports modified configuration | Follow [Recover from configuration conflicts](#recover-from-configuration-conflicts). |

To inspect runtime diagnostics, run this in an interactive terminal and press Ctrl+C when finished:

```sh
~/.local/bin/i3-calendar \
  --i3status-config ~/.config/i3status/config > /dev/null
```

Adjust the paths if needed. stdout is reserved for the bar's JSON stream; errors are written to stderr.

## Limitations and behavior

- **Local date:** the calendar follows the computer's local date, even if the selected status block displays a different time zone. Today's highlight updates after midnight.
- **One popup per user:** additional wrapper instances do not create a second calendar window while one is open.
- **Hidden bars:** the wrapper continues running while i3bar is hidden so that an open calendar remains responsive.
- **Integration scope:** automatic setup handles a plain i3status command. It does not merge arbitrary third-party status wrappers.
- **Calendar scope:** this is a date browser, without event storage, reminders, or account synchronization.

The wrapper implements the [i3bar JSON protocol](https://i3wm.org/docs/i3bar-protocol.html) and forwards SIGUSR1 to its child i3status process to refresh status values.

## Project layout

```text
i3-calendar/
├── config/
│   ├── calendar.conf      # Default calendar settings
│   ├── i3.conf            # Minimal i3 integration example
│   └── i3status.conf      # Minimal status configuration with a date block
├── src/
│   ├── calendar_app.py    # i3status wrapper and GTK calendar
│   └── manage.py          # Preflight, installation, and removal
├── install.sh
├── uninstall.sh
├── README.md
└── LICENSE
```

## Contributing

Bug reports and focused improvements are welcome. When reporting a problem, include your distribution, session type, Python/i3 versions, reproduction steps, and the relevant stderr output. Remove private paths or other personal details before sharing configuration snippets.

No automated test suite is included. Before submitting a change, check Python and shell syntax and manually verify the affected behavior in an i3/X11 session:

- Opening, toggling, Escape, and navigation across month/year boundaries.
- Today's highlight, dimmed adjacent dates, locale settings, and colors.
- Both outside-click modes and positioning on multiple monitors.
- Preservation of other status blocks and user edits during installation, updates, and removal.

## License

This project is licensed under the [MIT License](LICENSE).
