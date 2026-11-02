#!/bin/sh
set -eu
command -v python3 >/dev/null 2>&1 || {
    echo 'Python 3 is required.9+: Fedora: sudo dnf install python3; Debian/Ubuntu: sudo apt install python3' >&2
    exit 1
}
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# Validate sources before importing them; do not create bytecode during preflight.
python3 -B - "$SCRIPT_DIR" <<'PY'
import sys
from pathlib import Path
if sys.version_info < (3, 9):
    sys.exit('i3-calendar: Python 3.9 or newer is required. No files were changed.')
try:
    for name in ('calendar_app.py', 'manage.py'):
        path = Path(sys.argv[1]) / 'src' / name
        compile(path.read_text(), str(path), 'exec')
except (OSError, SyntaxError, UnicodeError) as exc:
    sys.exit(f'i3-calendar: invalid source files: {exc}. Installation cancelled.')
PY
exec python3 -B "$SCRIPT_DIR/src/manage.py" install --source "$SCRIPT_DIR" "$@"
