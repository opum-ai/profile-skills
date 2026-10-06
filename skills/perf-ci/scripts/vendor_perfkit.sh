#!/usr/bin/env bash
# vendor_perfkit.sh <dest-dir>: copy the stdlib-only perfkit engine (and the browser/xtrace helpers)
# into a repository so CI can run it without the plugin installed.
set -euo pipefail
dest="${1:?usage: vendor_perfkit.sh <dest-dir, e.g. tools/perfkit>}"
here="$(cd "$(dirname "$0")" && pwd)"
src="$here/../../perf-measure/scripts"
mkdir -p "$dest/perfkit"
cp "$src/perfkit.py" "$dest/"
cp "$src"/perfkit/*.py "$dest/perfkit/"
cp "$src/browser_trace.mjs" "$src/xtrace.sh" "$dest/"
version=$(python3 -c "import sys; sys.path.insert(0, '$dest'); import perfkit; print(perfkit.__version__)")
echo "vendored perfkit $version into $dest (python3 $dest/perfkit.py -h)"
