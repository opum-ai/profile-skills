# Profiling JavaScript / TypeScript (Node, Bun, Deno, builds)

Status as of Oct 2026:
- **Node 24** is LTS; Node 26 becomes LTS on 2026-10-28. `--cpu-prof` and `--heap-prof` are
  stable.
- **TypeScript 7** (the Go port, GA 2026-07) is a native binary, so `node --cpu-prof` can't
  see it.
- **Vitest 5** rewrote its bench API.
- **clinic.js** is unmaintained and **0x** is stale. `@platformatic/flame` is the active
  flame-graph tool.
- **Bun ≥1.3.7 and Deno** print Markdown profiles built for LLMs (`--cpu-prof-md`).

## Contents
1. Node CPU
2. Event loop and async
3. V8 optimization / deopts
4. Bun and Deno
5. Startup / import cost
6. TypeScript compiler, linters, bundlers, test runners
7. Source maps

## 1. Node CPU

```bash
node --cpu-prof --cpu-prof-dir=.perf/<c>/prof app.js args                 # .cpuprofile on normal exit
node --cpu-prof --cpu-prof-interval=100 --cpu-prof-dir=.perf/<c>/prof app.js   # µs; default 1000
NODE_OPTIONS="--cpu-prof --cpu-prof-dir=$PWD/.perf/<c>/prof" npm run build # every node process in the tree
node --import tsx --cpu-prof app.ts                                   # TS via a loader; or node ≥22.18/23.6 strips types natively
python3 $PK hotspots .perf/<c>/prof/*.cpuprofile --project-root .          # one file per process/worker: pick the big one
```
Gotchas:
- **The file is written only on normal exit.** `process.exit()` is fine. SIGKILL, a crash,
  or a test runner killing workers produces no file. For servers, handle SIGINT with
  `process.exit()`, or use the inspector API below.
- `--cpu-prof-dir` is relative to each process's cwd, so use an absolute path in
  `NODE_OPTIONS`.
- Worker threads write separate files.
- Line numbers in the profile are 0-based. `perfkit` reports them 1-based.
- Pseudo-frames:
  - `(garbage collector)`: a large share is allocation pressure, which is a finding.
  - `(program)`: native or V8-internal time.
  - `(idle)`: excluded from busy time.
  - Inlined callees are charged to their caller.
- Sample long enough to get at least a few thousand samples.

Programmatic, for one region (skips startup, works in servers and tests):
```js
import { Session } from 'node:inspector/promises'; import { writeFileSync } from 'node:fs';
const s = new Session(); s.connect();
await s.post('Profiler.enable'); await s.post('Profiler.setSamplingInterval', { interval: 100 });
await s.post('Profiler.start');
await workload();
const { profile } = await s.post('Profiler.stop');
writeFileSync('.perf/<c>/region.cpuprofile', JSON.stringify(profile));
```

The V8 tick log shows the C++/native split hidden under `(program)`:
```bash
node --prof app.js && node --prof-process isolate*.log > .perf/<c>/ticks.txt
```
Read the `[Bottom up (heavy) profile]` section.

Linux only: `perf record -g node --perf-basic-prof --interpreted-frames-native-stack app.js`
gives mixed JS and native stacks. On macOS, JS frames come out unsymbolized.

## 2. Event loop and async

```js
import { monitorEventLoopDelay, performance } from 'node:perf_hooks';
const h = monitorEventLoopDelay({ resolution: 10 }); h.enable();
let last = performance.eventLoopUtilization();
setInterval(() => {
  const elu = performance.eventLoopUtilization(last); last = performance.eventLoopUtilization();
  console.error(JSON.stringify({ p50: h.percentile(50) / 1e6, p99: h.percentile(99) / 1e6, max: h.max / 1e6, elu: +elu.utilization.toFixed(2) }));
  h.reset();
}, 2000).unref();
```
- **ELU ≈ 1 with high delay** means the main thread is CPU-bound. Profile it, then split the
  work or move it to `worker_threads` / Piscina.
- **High latency with low ELU** means waiting on I/O or a downstream service. Look at
  sequential awaits (`for … await`) that could use `Promise.all` with a bound.
- `node --trace-sync-io app.js` warns on sync I/O after the first tick.
- Prefer `diagnostics_channel` (undici/http publish request events) over `async_hooks`,
  which is expensive.

## 3. V8 optimization / deopts

Only look at deopts when a hot function's self time is unexpectedly high for what it does.
```bash
node --trace-opt --trace-deopt app.js 2>&1 | grep -E 'deoptimiz|bailout' | sort | uniq -c | sort -rn | head
npx dexnode app.js     # Deopt Explorer logs for VS Code
```
What to look for:
- **Repeated deopts of the same function** (a deopt loop).
- **Megamorphic property access** (more than 4 object shapes at one site). It comes from
  objects built with different key orders, `delete`, or fields added after construction.
- **Holey or mixed-element arrays.**

Ignore one-off deopts during warmup. Obsolete folklore (try/catch, `arguments`, forEach vs
for) is not worth "fixing".

## 4. Bun (measured on Bun 1.3.14) and Deno

```bash
bun --cpu-prof-md --cpu-prof-dir=.perf/<c>/prof script.ts   # Markdown: hot functions (self), call tree, per-function detail; native frames shown
bun --cpu-prof --cpu-prof-dir=.perf/<c>/prof script.ts      # Chrome .cpuprofile → perfkit hotspots
bun --heap-prof-md script.ts                                # top types by retained size + retainer chains
bun --heap-prof --heap-prof-dir=.perf/<c>/heap script.ts    # V8-format .heapsnapshot
bun test                                                    # runs node:test-style suites; --coverage for line coverage
deno run --cpu-prof --cpu-prof-md --cpu-prof-dir=.perf/<c>/prof main.ts
```
- **Use Bun profiles to locate hotspots, never for timings.** On this M4 the measured overhead was +27% at the
  default 1 ms interval and +74% at 100 µs, against about +0.8% for `node --cpu-prof`. Bun issue #44077 (open) reports
  event-loop idle time counted as JS self time. Timing claims come from mitata or `perfkit abtest`.
- **When code runs on both runtimes, cross-check the hot frames on Node.** JavaScriptCore (Bun) and V8 differ in
  inlining, GC and deopts, and the same code can be several times slower on one of them. The resolver fixture here
  ran 3× slower on Bun. Profile and benchmark on the runtime you ship. If you ship on both, A/B on both.
- Bun's `.cpuprofile` file names carry a non-wall-clock timestamp. Pick the newest with `ls -t`.
- In `--cpu-prof-md`, trust Self%. Total% over-counts recursive functions.

## Flame graphs: @platformatic/flame (ADR-0006)

```bash
npx -y @platformatic/flame run --output .perf/<c>/flame app.js args   # pprof .pb + standalone HTML flame graph on exit
npx -y @platformatic/flame run --manual server.js                    # toggle with: kill -USR2 <pid>
```
- Flame graphs are for humans. You reason from `perfkit hotspots` on the `.cpuprofile`.
- A flame graph shows distribution, not efficiency. A differential flame graph is drawn from the *after* profile, so
  code that disappeared is invisible unless you also look at the negated view.
- Check exact flags with `npx @platformatic/flame --help`; they changed across 2025–26 releases.

## 5. Startup / import cost

```bash
hyperfine -N --warmup 5 'node dist/cli.js --version'          # or perfkit abtest
node --cpu-prof --cpu-prof-interval=50 dist/cli.js --version  # look for compileFunction / require / module loading
NODE_DEBUG=module node dist/cli.js --version 2>&1 | wc -l      # module resolution volume
```
Fixes:
- lazy `await import()` for rare subcommands;
- remove barrel files (an `index.ts` that re-exports everything loads everything);
- bundle CLIs to one file;
- `module.enableCompileCache()` or `NODE_COMPILE_CACHE=dir` (Node ≥22.1);
- no sync work at import time.

## 6. TypeScript compiler, linters, bundlers, test runners

**TS ≤6 (JS tsc):**
```bash
npx tsc -p . --noEmit --extendedDiagnostics        # Types, Instantiations, Check time, Files
npx tsc -p . --noEmit --generateTrace .perf/<c>/ts-trace --incremental false && npx @typescript/analyze-trace .perf/<c>/ts-trace
node --cpu-prof node_modules/typescript/lib/tsc.js -p . --noEmit
```
- A huge `Instantiations` count points at type-level libraries (zod, trpc, drizzle), deep
  conditional types, or giant unions.
- A large `Files` count points at a leaky `include` or missing `skipLibCheck`.

**TS 7 (native):**
- `--extendedDiagnostics` works.
- `--singleThreaded` gives a fair comparison or a repro; `--checkers N` sets parallelism.
- Profile with `samply record npx tsc -p .`. `--generateTrace` support is unverified.

**ESLint:** `TIMING=1 npx eslint .` gives per-rule times. Then
`node --cpu-prof node_modules/eslint/bin/eslint.js .`.

**Bundlers:**
- Vite 8 / Rolldown: `vite build --debug`; JS plugins usually dominate
  (`vite-plugin-inspect`).
- Rspack 2: `RSPACK_PROFILE=OVERVIEW rspack build`, then Rsdoctor.
- webpack: `node --cpu-prof node_modules/webpack/bin/webpack.js` plus a persistent
  filesystem cache.

**Test runners:**
- `vitest --reporter=verbose` timings, or `jest --verbose`.
- Profile with `NODE_OPTIONS=--cpu-prof` and `--pool=forks --poolOptions.forks.singleFork`,
  so workers exit normally and write their profiles.

## 7. Source maps

Profiles of transpiled code point at JS positions. Map hot `url:line` back with
`source-map`'s `SourceMapConsumer.originalPositionFor`, or read the emitted JS around that
line. Usually the function name is enough to find the TS source.
