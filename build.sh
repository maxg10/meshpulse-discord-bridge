#!/usr/bin/env bash
# Package the plugin as a .meshplugin archive (a plain ZIP).
set -euo pipefail

cd "$(dirname "$0")"

name=$(python3 -c "import json; print(json.load(open('plugin.json'))['id'].split('/')[1])")
version=$(python3 -c "import json; print(json.load(open('plugin.json'))['version'])")
archive="${name}-${version}.meshplugin"

rm -f "$archive"
zip -r "$archive" \
    plugin.json requirements.txt backend/ frontend/ README.md LICENSE \
    -x '*__pycache__*' '*.pyc' '*.DS_Store' >/dev/null

printf '%s\n' "$archive"
