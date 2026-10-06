#!/bin/bash
# setup_ws.sh <iteration-dir> <eval-name> : copy (or scaffold) the fixture into with_skill/ and without_skill/ outputs/repo
set -euo pipefail
it="$1"; name="$2"; here="$(cd "$(dirname "$0")" && pwd)"
fixture=$(python3 -c "import json,sys; e=[e for e in json.load(open('$here/evals.json'))['evals'] if e['name']=='$name'][0]; print(e['fixture'])")
for arm in with_skill without_skill; do
  dest="$it/eval-$name/$arm/outputs/repo"; rm -rf "$dest"; mkdir -p "$(dirname "$dest")"
  if [ -x "$here/fixtures/$fixture/scaffold.sh" ]; then "$here/fixtures/$fixture/scaffold.sh" "$dest" >/dev/null
  else cp -R "$here/fixtures/$fixture" "$dest"; (cd "$dest" && git init -q && git add -A && git -c user.email=e@e -c user.name=e commit -qm "initial" ); fi
done
echo "ready: $it/eval-$name"
