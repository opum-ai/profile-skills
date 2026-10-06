# Correctness guards and anti-gaming checks

ECCO found that no method of the time improved efficiency without sacrificing correctness.
The guard is what makes a speedup admissible. Build it before the first change, and don't
change it during the loop.

## 0. Pin before you change (test-skills hand-off)

Before the first change, the code you will touch must be **pinned**:
- **Coverage of the changed lines** (R3), for example:
  - `uv run --with coverage coverage run -m pytest -q && coverage report -m --include='pkg/hot.py'`
  - Node: `npx c8 --include=src/hot.ts node --test`
  - Bun: `bun test --coverage`

  Lines you will change that no test executes are unpinned. Pin them first, with
  table/property tests through test-plan's admission rules, or with the equivalence harness
  below.
- **Kill matrix** (R4+): with test-skills installed,
  `python3 <test-skills>/skills/test-audit/scripts/tmx.py collect-pytest --src <changed module> --tests tests -o .perf/<c>/kills-before.json`.
  Re-collect after the change. Any mutant killed before and surviving after is a lost
  obligation, and the change is reverted.
- Record the counts (tests, coverage %, kills) in SCOPE.md and the Quest task. The same
  checks must pass, with no fewer kills, after every kept experiment.

## 1. Layers of guard (use every layer that applies)

1. **The project's test suite.** Run the relevant subset in the loop and the full suite at the
   end. Record counts (`212 passed`). A test that starts failing is a revert, never a test edit.
2. **Output equivalence on the workload.** For CLIs and scripts,
   `perfkit abtest --require-same-output` compares stdout digests across arms on every run.
   For files, diff the output files (`cmp`, `diff -r`, or a canonicalizing script).
3. **Differential harness on generated inputs** (R4+, recommended at R3 when tests are thin).
   Import the incumbent and the candidate side by side and compare on random and edge inputs.
4. **Secondary-metric checks.** Memory (peak RSS from `abtest --all-metrics`), p99 for
   services, startup, bundle size, CLS for frontend changes. LLM DOM "optimizations" often
   introduce layout shift.

### Python differential harness

```python
# .perf/<c>/equiv.py: run with the candidate checkout as cwd
import importlib.util, random, sys
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m); return m
old = load(".perf/wt-incumbent/app/report.py", "old_report")
new = load("app/report.py", "new_report")
rng = random.Random(0)
cases = [[], [1], [1, 1], list(range(1000))] + [[rng.randint(-5, 5) for _ in range(rng.randint(0, 50))] for _ in range(500)]
for c in cases:
    a, b = old.dedupe(list(c)), new.dedupe(list(c))   # copies: detect input mutation separately
    assert a == b, (c[:20], a[:20], b[:20])
print("equivalent on", len(cases), "cases")
```

Hypothesis (`@given`) works too, and shrinks failures for you. Keep the harness in
`.perf/<c>/`, not in `tests/`, unless it earns a place under test-plan's admission rules.

### JS/TS differential harness

```js
// .perf/<c>/equiv.mjs (run from the repo root: node .perf/<c>/equiv.mjs)
import * as oldM from '../wt-incumbent/dist/index.js';
import * as newM from '../../dist/index.js';
import assert from 'node:assert/strict';
let seed = 1; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
for (let i = 0; i < 500; i++) {
  const input = Array.from({ length: Math.floor(rnd() * 50) }, () => Math.floor(rnd() * 10));
  assert.deepStrictEqual(newM.dedupe([...input]), oldM.dedupe([...input]));
}
console.log('equivalent');
```

fast-check's `fc.assert(fc.property(...))` gives shrinking.

### Bash: identical output and exit status

```bash
for f in fixtures/*.csv .perf/<c>/holdout/*.csv; do
  diff <(.perf/wt-incumbent/nightly.sh "$f"; echo "exit=$?") <(./nightly.sh "$f"; echo "exit=$?") || echo "DIFF on $f"
done
```

Also test empty input, a missing file, and names with spaces or globs. Shell rewrites
regularly break quoting and error paths.

## 2. Semantics checklist (what "same behavior" includes)

Before keeping a change, check each item that applies:
- **Order.** Is output order preserved? Replacing a `list` with a `set`, or `dict` with a hash
  join, can reorder results. `dict.fromkeys` keeps insertion order; `set` does not.
- **Duplicates and identity.** Dedup by `==` vs `is`; object identity returned to callers.
- **Floating point.** Vectorizing (numpy, SIMD) or reordering sums changes rounding. Decide
  whether bit-equality or a tolerance is the contract, and state it.
- **Errors.** The same exception types and messages for bad input, and the same exit codes.
  Fast paths often skip validation.
- **Laziness and streaming.** Generators turned into lists change memory and time-to-first-
  result. Reading a whole file breaks on inputs larger than memory.
- **Input mutation.** Sorting in place or reusing buffers can mutate caller data.
- **Side effects.** Logging, metrics, file writes, the count of network calls. Batching
  changes partial-failure semantics.
- **Concurrency.** Shared caches, memoization across threads, async fan-out (ordering,
  backpressure, rate limits), lock removal. Hand these to proof-skills' formal-verify at R3+.
- **Locale, encoding, time.** `LC_ALL=C` speeds up `sort` and `grep` but changes collation and
  case rules. Use it only where bytes are the contract.
- **Platform.** GNU vs BSD tools, and bash 3.2 vs 5 on macOS. A shell rewrite must still run
  on the target shell.

## 3. Anti-gaming checks (run before claiming any result)

Published agent-perf benchmarks now run "hack detectors" because agents game evaluators:
memoizing benchmark inputs, special-casing fixtures, hijacking the harness. Check yourself:

- `git diff --stat` shows no changes to the benchmark, workload files, timing harness, guard
  tests or `perf-policy.toml`. If one changed for a legitimate reason, it was its own logged
  experiment, followed by a new baseline.
- No cache, memo or precomputed table keyed on the benchmark's inputs survives across runs
  when production would not hit it. Process-level caches are fine if production processes are
  long-lived. Disk caches must be cleared between arms (`--prepare`).
- No branch tests for fixture-specific values: file names, sizes, magic constants.
- No work is skipped just because the benchmark doesn't check its result. Example: computing
  a column that the benchmark doesn't print but production uses.
- **The hold-out workload confirms the gain.** It has a different seed, size or file, and you
  never profiled or tuned on it. A large gap between the main and hold-out speedups is a red
  flag.
- The workload is not smaller than at baseline, and the input is the same bytes. Record a
  checksum in SCOPE.md.

## 4. Hold-out workloads

Create the hold-out set at scope time:
- the same generator with another seed;
- a size 2–4× larger, which exposes complexity changes the main size hides;
- one real-world sample if the user has one.

Measure it only at the baseline and at the final confirmation. If the user gave only one
input, generate the hold-out yourself and say so.
