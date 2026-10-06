#!/usr/bin/env bash
set -euo pipefail
src_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
app_dir="${XDG_DATA_HOME:-$HOME/.local/share}/ddc-input-switch"
bin_dir="$HOME/.local/bin"
desktop_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$app_dir" "$bin_dir" "$desktop_dir"
install -m 755 "$src_dir/ddc-input-switch.py" "$app_dir/ddc-input-switch.py"
ln -sfn "$app_dir/ddc-input-switch.py" "$bin_dir/ddc-input-switch"
python3 - "$app_dir/ddc-input-switch.py" "$desktop_dir/ddc-input-switch.desktop" <<'PY'
import sys
from pathlib import Path
# Desktop Entry Exec quoting is distinct from shell quoting.
path = sys.argv[1]
quoted = '"' + path.replace('\\', '\\\\\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
Path(sys.argv[2]).write_text(f'''[Desktop Entry]
Type=Application
Name=Monitor Input Switch
Comment=Switch between two monitor inputs using DDC/CI
Exec={quoted} gui
Icon=video-display
Terminal=false
Categories=Utility;HardwareSettings;
Actions=Toggle;InputA;InputB;

[Desktop Action Toggle]
Name=Toggle monitor input
Exec={quoted} toggle

[Desktop Action InputA]
Name=Switch to Input A
Exec={quoted} a

[Desktop Action InputB]
Name=Switch to Input B
Exec={quoted} b
''')
PY
if command -v update-desktop-database >/dev/null; then
    update-desktop-database "$desktop_dir"
fi
printf 'Installed. Open Monitor Input Switch from your application menu.\n'
