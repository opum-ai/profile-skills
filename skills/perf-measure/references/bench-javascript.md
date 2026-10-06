# JavaScript / TypeScript benchmark harnesses

| Need | Pick (ADR-0006: tools collect, perfkit decides) |
|---|---|
| Microbenchmark on Node **and** Bun | **mitata** `run({ format: 'json' })` → `perfkit compare` (DCE detection, `do_not_optimize`, GC control). No commits in about 20 months, which is a watched risk |
| Fallback when mitata is unavailable or broken | **tinybench** 6.x (active; assign results to a sink) |
| Already on Vitest | `vitest bench`; **the API differs between Vitest 4 and 5** |
| Deno | `deno bench` |
| Bun | mitata (Bun's recommendation) |
| Whole CLI / process / build | `perfkit abtest` or hyperfine |
| CI gate | CodSpeed (`@codspeed/vitest-plugin` / `tinybench-plugin`; Vitest 5 support pending), or perfkit compare in a same-job A/B |
| Don't use | benchmark.js (archived 2024), hand-rolled `Date.now()` loops |

## mitata

```js
// bench/dedupe.bench.mjs — run: node --expose-gc bench/dedupe.bench.mjs
import { bench, summary, run, do_not_optimize } from 'mitata';
import { dedupe as oldDedupe } from '../../wt-incumbent/dist/index.js';
import { dedupe as newDedupe } from '../dist/index.js';
const data = makeData(10_000, 1);          // generated outside timing, seeded
summary(() => {
  bench('old', () => do_not_optimize(oldDedupe(data)));
  bench('new', () => do_not_optimize(newDedupe(data)));
});
const r = await run({ format: 'json', print: (s) => process.stdout.write(s) });   // node --expose-gc b.mjs > .perf/<c>/mitata.json
// then: python3 $PK compare .perf/<c>/mitata.json --baseline old   (samples are per-iteration ns; unpaired)
```
- Use `.gc('inner')` for allocation-heavy cases.
- Computed parameters (`function* () { yield { [0]() {...}, bench(a) {...} } }`) defeat
  loop-invariant hoisting.
- mitata flags suspiciously fast results (`!`), which usually means DCE.
- **Both arms in one process share JIT feedback and the heap.** For sensitive comparisons,
  run each arm in a fresh process (`perfkit abtest` with a per-arm driver), or at least
  alternate the order.

## tinybench

```js
import { Bench } from 'tinybench';
const b = new Bench({ time: 1000, warmupTime: 200 });
let sink; b.add('new', () => { sink = newDedupe(data); });
await b.run(); console.table(b.table());
// raw samples for perfkit: b.tasks.map(t => ({ name: t.name, samples: t.result.samples }))  (ms per iteration; verify field names on your version)
```
tinybench has no DCE protection, so assign results to a module-level sink.

## Vitest bench

**Vitest ≤4:**
```ts
import { bench, describe } from 'vitest';
describe('dedupe', () => { bench('new', () => { newDedupe(data); }); });
```
Run `vitest bench --outputJson .perf/<c>/main.json`, then `vitest bench --compare .perf/<c>/main.json`.

**Vitest 5 (2026-09):** `bench` is a test-context fixture inside `*.bench.ts`.
`--outputJson` / `--compare` were removed.
```ts
import { test, expect } from 'vitest';
test('dedupe', async ({ bench }) => {
  const r = await bench.compare(bench('old', () => oldDedupe(data)), bench('new', () => newDedupe(data)));
  expect(r.get('new')).toBeFasterThan(r.get('old'));
});
```
Check the installed version (`npx vitest --version`) before writing benchmarks. Signatures
are from release notes; verify them against your installed docs.

## Deno / Bun

```ts
Deno.bench({ name: 'new', group: 'dedupe', baseline: false }, () => { newDedupe(data); });
// deno bench --json > .perf/<c>/deno.json
```
Bun: use mitata (`bun bench/x.bench.mjs`). `Bun.nanoseconds()` is available for custom
timers.

## JIT and GC pitfalls

1. **Dead-code elimination.** Consume the result.
2. **Constant folding / hoisting.** Generate inputs outside the timing and vary them.
3. **Warmup and tier-up** (Ignition → Sparkplug → Maglev → TurboFan). Report steady state,
   and report cold start separately if startup matters.
4. **Monomorphic microbenchmarks.** Production may be megamorphic, so feed realistic object
   shapes.
5. **Order effects.** The first benchmark in a process warms shared helpers. Randomize, or
   use fresh processes.
6. **GC noise.** `--expose-gc` plus mitata's GC control, and report allocations
   (`--heap-prof`) alongside time.
7. **Timer resolution in browsers.** `performance.now()` is coarsened, so batch iterations.

## TypeScript builds and type-checks as benchmarks

```bash
python3 $PK abtest --names base,cand --a "npx tsc -p . --noEmit" --cwd-a ../wt-incumbent \
  --b "npx tsc -p . --noEmit" --runs 10 --warmup 1
```
Keep caches comparable: disable incremental (`--incremental false`), or clear
`tsbuildinfo` with `--prepare`. For TS 7, add `--singleThreaded` when you need a fair
comparison of CPU work.
