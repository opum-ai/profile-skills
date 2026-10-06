#!/usr/bin/env bash
# prove_ci_gate.sh <work-dir>: prove the perf-ci gate both ways on the fastparse fixture, exactly as CI runs it.
#
# The fixture gets the skill's vendored perfkit, a perf-policy.toml with a benchmark, and its own copy of the
# CI steps (suite + gate with --policy-ref at the base commit). Four PR heads are judged against the same base:
#   clean        docstring-only change                      -> PASS
#   regression   parse() validates each line with an uncompiled regex first -> FAIL (regressed)
#   cheat        the same regression + the PR raises max_regression to 9.0 and shrinks the benchmark -> FAIL
#   small        a ~2% slowdown, below the tolerance        -> PASS (states the detection floor)
# Exit 0 only if every case gets its predicted verdict. Writes <work-dir>/ci-gate-proof.json.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
work="${1:?work dir}"; rm -rf "$work"; mkdir -p "$work"
base="$work/repo"
cp -R "$root/evals/fixtures/py-ci-lib" "$base"
cd "$base"
git init -q && git config user.email e@e && git config user.name e
"$root/skills/perf-ci/scripts/vendor_perfkit.sh" tools/perfkit >/dev/null
mkdir -p benchmarks
cat > benchmarks/bench_parse.py <<'EOF'
"""Fixed workload for the perf gate: parse_many over 20k mixed lines; prints a digest of the parsed records."""
import hashlib, json, random, sys
sys.path.insert(0, ".")
from fastparse import parse_many
rng = random.Random(1)
levels = ["debug", "info", "warn", "error"]
lines = []
for i in range(int(sys.argv[1]) if len(sys.argv) > 1 else 20000):
    kv = " ".join(f"k{j}={rng.randint(0, 999)}" for j in range(rng.randint(1, 8)))
    lines.append(f"{1760000000 + i} {rng.choice(levels)} event {i} | {kv} msg=\"hello \\\"x\\\" {i}\"" if i % 33 else "")
recs = parse_many(lines)
print(hashlib.sha256(json.dumps(recs, sort_keys=True).encode()).hexdigest()[:16], len(recs))
EOF
cat > perf-policy.toml <<'EOF'
version = 1
rigor = "R3"
[stats]
min_effect = 0.03
max_regression = 0.05     # A/A on this machine: |change| <= 2% (see prove_ci_gate.sh A/A step)
min_runs = 10
max_runs = 30
[[benchmark]]
name = "parse-many-20k"
cmd = "python3 benchmarks/bench_parse.py 20000"
paths = ["fastparse/**"]
runs = 12
warmup = 1
EOF
printf '.perf/\nperf-ci/\n__pycache__/\n' > .gitignore
git add -A && git commit -qm "base: fastparse + perf gate" && base_sha=$(git rev-parse HEAD)
git rm -r -q --cached fastparse/__pycache__ tests/__pycache__ 2>/dev/null; git commit -qm "untrack pyc" 2>/dev/null; base_sha=$(git rev-parse HEAD)
git worktree add -q "$work/base" "$base_sha"

run_case() { # name expected(PASS|FAIL) mutate-fn
  local name="$1" want="$2" fn="$3"
  git checkout -q -B "case-$name" "$base_sha"
  "$fn"
  git commit -qam "case $name"
  local out="$work/out-$name"
  python3 tools/perfkit/perfkit.py suite --policy perf-policy.toml --policy-ref "$base_sha" \
      --base "$work/base" --head . --out-dir "$out" > "$work/$name.suite.log" 2>&1
  python3 tools/perfkit/perfkit.py gate --policy perf-policy.toml --policy-ref "$base_sha" \
      --compare "$out/comparisons.json" --metrics "$out/metrics.json" --json "$out/gate.json" > "$work/$name.gate.log" 2>&1
  local code=$?
  local got=$([ $code -eq 0 ] && echo PASS || echo FAIL)
  local verdict=$(python3 -c "import json;c=json.load(open('$out/comparisons.json'))['comparisons'][0];print(c['verdict'], round(c['change_pct'],1), [round(x,3) for x in c['ratio_ci']], c['baseline']['n'])")
  printf '%-11s want %-4s got %-4s  %s\n' "$name" "$want" "$got" "$verdict"
  printf '{"case":"%s","want":"%s","got":"%s","detail":"%s"},\n' "$name" "$want" "$got" "$verdict" >> "$work/results.jsonl"
  [ "$got" = "$want" ]
}
clean()      { sed -i '' '1s/^/# docstring-only change\n/' fastparse/core.py; }
regression() { python3 - <<'EOF'
p = "fastparse/core.py"; s = open(p).read()
s = s.replace('    ts, level, rest = line.split(" ", 2)', '    import re as _re\n    if not _re.match(r"^\\d+ (debug|info|warn|error) ", line):\n        raise ValueError("bad line")\n    _re.purge()\n    ts, level, rest = line.split(" ", 2)')
open(p, "w").write(s)
EOF
}
cheat()      { regression; sed -i '' 's/^max_regression = 0.05.*/max_regression = 9.0/' perf-policy.toml; sed -i '' 's/bench_parse.py 20000/bench_parse.py 1000/' perf-policy.toml; }
small()      { python3 - <<'EOF'
p = "fastparse/core.py"; s = open(p).read()
s = s.replace('    return [parse(l) for l in lines if l.strip()]', '    out = [parse(l) for l in lines if l.strip()]\n    _ = [len(r["fields"]) for r in out]\n    return out')
open(p, "w").write(s)
EOF
}
: > "$work/results.jsonl"
fail=0
run_case clean PASS clean || fail=1
run_case regression FAIL regression || fail=1
run_case cheat FAIL cheat || fail=1
run_case small PASS small || fail=1
python3 - "$work" <<'EOF'
import json, sys
w = sys.argv[1]
rows = [json.loads(l.rstrip(",\n")) for l in open(f"{w}/results.jsonl") if l.strip()]
json.dump({"cases": rows, "proven": all(r["want"] == r["got"] for r in rows)}, open(f"{w}/ci-gate-proof.json", "w"), indent=1)
EOF
[ $fail -eq 0 ] && echo "CI GATE PROVEN" || echo "CI GATE NOT PROVEN"
exit $fail
