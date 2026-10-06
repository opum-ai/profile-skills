---
# yaml-language-server: $schema=../../.lore/schemas/reference.schema.json
type: Reference
title: "Research notes: JavaScript, TypeScript and browser performance"
tags:
  - research
summary: Node/Bun/Deno profiling, V8, benchmark harnesses, TypeScript and bundler performance, browser tracing, web vitals and bundles, as of Oct 2026.
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:00:48.476Z
---

# Research notes: JavaScript, TypeScript and browser performance

Raw research notes gathered 2026-10-05 by three parallel research passes (web sources cited inline; items not confirmed against a primary source are marked unverified). The distilled design input is [the state-of-the-art summary](state-of-the-art-in-performance-profiling-and-agent-driven-optimization.md).


*Research snapshot: 2026-10-05. Audience: an AI coding agent (Claude Code) on macOS (Apple Silicon) and Linux CI.*
*Legend: **[verified]** = checked against a primary source or run locally during this research; **unverified** = could not confirm, treat as a hint.*

Local sanity check performed while writing: Node v24.20.0 and Bun 1.3.14 on macOS arm64. `node --cpu-prof` + the parser script in §1.6, and `bun --cpu-prof-md`, were both run and produced the output shown.

---

## 0. Current landscape (October 2026): versions and status

| Thing | Status (Oct 2026) | Source |
|---|---|---|
| Node.js | 24.x = Active LTS; **26.x** released Apr/May 2026 (V8 14.6), becomes **LTS on 2026-10-28**; 25.x = odd/Current | https://nodejs.org/en/blog/announcements/evolving-the-nodejs-release-schedule , https://nodejsdesignpatterns.com/blog/whats-new-in-nodejs-26/ |
| `--cpu-prof*` / `--heap-prof*` flags | **Stable** since v22.4.0 / v20.16.0 | https://nodejs.org/api/cli.html |
| TypeScript | **TS 7.0 (Go native port, "Corsa") GA 2026-07-08**; npm `typescript@latest` = 7.0.x, binary is still `tsc`. 7.1 beta ~2026-10-06, stable ~2026-11-24. No Strada (JS) compiler API in 7.0; `@typescript/typescript6` is the side-by-side bridge | https://typescriptpro.com/blog/typescript-version-7-2026-07-08 , https://visualstudiomagazine.com/articles/2026/04/21/typescript-7-0-beta-arrives-on-go-based-foundation-with-10x-speed-claim.aspx |
| Vite | **Vite 8 (2026-03-12) uses Rolldown** for dev+build; Rolldown 1.0 stable 2026-05 | https://vite.dev/blog/announcing-vite8 |
| Rspack | 2.x (2.1 / 2.2.x in 2026) | https://rspack.rs/blog/announcing-2-1 |
| Vitest | **Vitest 5.0 (2026-09-03) rewrote bench API** (fixture-based; `--compare`/`--outputJson` removed) | https://vitest.dev/blog/vitest-5 |
| tinybench | 6.x (6.2.0 latest seen); v5 dropped Node 18 | https://github.com/tinylibs/tinybench/releases |
| mitata | actively maintained, cross-runtime; `@mitata/counters` for HW counters | https://github.com/evanwashere/mitata |
| benchmark.js | **archived 2024-04-11** — do not use for new work | https://github.com/bestiejs/benchmark.js/ |
| clinic.js | **not actively maintained**; README warns results may be inaccurate on modern Node | https://github.com/clinicjs/node-clinic |
| 0x | 6.0.0, low activity; successor-ish: `@platformatic/flame` (pprof + HTML flamegraphs, Sep 2025, active) | https://www.npmjs.com/package/0x , https://blog.platformatic.dev/introducing-next-gen-flamegraphs-for-nodejs |
| Bun | `--cpu-prof` since **1.3.2** (Nov 2025); `--cpu-prof-md`, `--heap-prof`, `--heap-prof-md`, `node:inspector` Profiler since **1.3.7** | https://bun.com/blog/bun-v1.3.2 , https://bun.com/blog/release-notes/bun-v1.3.7 |
| Deno | `--cpu-prof`, `--cpu-prof-md`, `--cpu-prof-flamegraph` (SVG) built in | https://docs.deno.com/runtime/fundamentals/cpu_profiling/ |
| Chrome DevTools MCP | **Stable** (Chrome 149, June 2026); v1.10.0 on 2026-09-23; perf trace + heap snapshot + Lighthouse tools | https://github.com/ChromeDevTools/chrome-devtools-mcp , https://developer.chrome.com/blog/new-in-devtools-149 |
| Lighthouse | 13 (Oct 2025) moved to "insight" audits, removed several legacy audits; LHCI 0.15.1 (2025-06), slow but not archived | https://www.searchenginejournal.com/google-lighthouse-13-launches-with-insight-based-audits/558051/ |
| web-vitals | **v6** (soft-navigation support; 6.2.3 latest seen); v5 removed `onFID` | https://github.com/GoogleChrome/web-vitals |
| React Compiler | **1.0 stable 2025-10-07** | https://react.dev/blog/2025/10/07/react-compiler-1 |
| k6 | 1.0 (May 2025, native TS), **2.0 (May 2026)** | https://grafana.com/blog/k6-2-0-release/ |
| CodSpeed (JS) | `@codspeed/vitest-plugin`/`tinybench-plugin` ≥5; mode `simulation` (formerly `instrumentation`) or `walltime`; **Vitest 5 support PR #86 still a draft as of 2026-09-30** | https://codspeed.io/docs/instruments/cpu , https://github.com/CodSpeedHQ/codspeed-node/pull/86 |
| memlab | maintained; ships `AI.md` and `@memlab/mcp-server` | https://github.com/facebook/memlab/blob/main/AI.md |

**Agent rule of thumb:** always print tool versions (`node -v`, `npx tsc -v`, `npx vitest --version`, Chrome version) into any perf log — tool upgrades (Lighthouse 13, Vitest 5, TS 7) change numbers and APIs.

---

## 1. Node.js CPU profiling

### 1.1 `--cpu-prof` (default first choice — headless, file-based, agent-friendly) [verified]

```bash
node --cpu-prof --cpu-prof-dir=./prof --cpu-prof-name='app.${pid}.cpuprofile' app.js
node --cpu-prof --cpu-prof-interval=100 app.js   # µs; default 1000. 100 = finer, bigger file, more overhead
# Profile a CLI/build tool that is itself Node:
node --cpu-prof ./node_modules/typescript/lib/tsc.js -p .      # TS <=6 only (TS7 is native)
node --cpu-prof ./node_modules/eslint/bin/eslint.js .
node --cpu-prof ./node_modules/webpack/bin/webpack.js
# Everything spawned via npm scripts / child processes (each process writes its own file):
NODE_OPTIONS="--cpu-prof --cpu-prof-dir=$PWD/prof" npm run build
```
Gotchas:
- Profile is written **only at normal exit** (`process.exit()` is fine; SIGKILL / crash = no file). For servers, handle SIGINT and call `process.exit()`, or use the inspector API (§1.3).
- Default name `CPU.${yyyymmdd}.${hhmmss}.${pid}.${tid}.${seq}.cpuprofile`; worker threads produce separate files (tid differs). Use `--cpu-prof-dir` (or `--diagnostic-dir`) so the agent can glob them.
- `--cpu-prof-dir` relative to cwd of *each* process — use an absolute path with `NODE_OPTIONS`.
- Sampling profiler: functions under 1 sample are invisible; run the workload long enough (≥ a few seconds, ≥ ~2–5k samples).
- Pseudo-nodes: `(garbage collector)`, `(program)` (native/V8 internal not attributed to JS), `(idle)`, `(root)`. In the local test, GC was **34%** of samples for a string-concat loop — a big `(garbage collector)` share is itself a finding (allocation pressure).
- Inlined functions are attributed to the caller (TurboFan/Maglev inlining) — a hot "caller" may really be a small inlined callee.

### 1.2 `--prof` + `--prof-process` (V8 tick log) 
```bash
node --prof app.js                              # writes isolate-0x...-v8.log
node --prof-process --preprocess isolate*.log > processed.json   # JSON for tools (e.g. speedscope / deoptexplorer)
node --prof-process isolate*.log > ticks.txt    # text: [Summary] / [JavaScript] / [C++] / [Bottom up (heavy) profile]
```
Useful when you need **C++/native split** (shared library ticks, GC, builtins) that `.cpuprofile` hides under `(program)`. Text output is grep-able for an agent (`[Bottom up (heavy) profile]` section). Less convenient than `--cpu-prof` otherwise. (https://nodejs.org/en/learn/getting-started/profiling)

### 1.3 Programmatic profiling with `node:inspector` (scoped to a code region) [verified API]
```js
import { Session } from 'node:inspector/promises';
import { writeFileSync } from 'node:fs';
const s = new Session(); s.connect();
await s.post('Profiler.enable');
await s.post('Profiler.setSamplingInterval', { interval: 100 }); // µs, must be before start
await s.post('Profiler.start');
await workloadUnderTest();
const { profile } = await s.post('Profiler.stop');
writeFileSync('region.cpuprofile', JSON.stringify(profile));
// Heap sampling the same way: HeapProfiler.startSampling / stopSampling -> .heapprofile
```
Use when only one phase matters (e.g., exclude startup) or for long-running servers (start/stop via an admin endpoint or signal). Docs: https://nodejs.org/api/inspector.html. Bun ≥1.3.7 implements the same `Profiler.*` API.

### 1.4 Interactive: Chrome DevTools / VS Code
- `node --inspect app.js` (or `--inspect-brk`), open `chrome://inspect` → "Open dedicated DevTools for Node" → Performance/Profiler tab.
- Any `.cpuprofile` can be dragged into Chrome DevTools Performance panel, VS Code (built-in viewer), https://www.speedscope.app (`npx speedscope file.cpuprofile`), or **cpupro** (`npx cpupro file.cpuprofile`, discoveryjs; good for large profiles — status unverified for 2026).
- Agents can't look at flame graphs well — prefer text summaries (§1.6) and only open GUIs for humans.

### 1.5 Flamegraph tools
- **0x**: `npx 0x -- node app.js` → HTML flamegraph; uses `--prof` internally. Works on macOS/Linux, low maintenance (6.0.0).
- **@platformatic/flame** (active): `npx @platformatic/flame run server.js` (auto-start, saves on exit), `flame run --manual server.js` + `kill -USR2 <pid>` to toggle, `flame generate cpu-profile-*.pb`. Outputs **pprof `.pb`** + standalone HTML; has heap profiling too (https://blog.platformatic.dev/announcing-heap-profiling-support-in-platformaticflame-and-watt-runtime). pprof output means `go tool pprof -top file.pb` gives text tables for agents.
- **clinic.js** (`clinic doctor|flame|bubbleprof|heapprofiler`): **unmaintained** — avoid as a default; may still run on Node 20/22 but results may be inaccurate (repo notice).

### 1.6 Parsing `.cpuprofile` programmatically (agent essential) [verified locally]
Format (Chrome DevTools Protocol `Profiler.Profile`): `{ nodes: [{id, callFrame:{functionName,url,lineNumber,columnNumber,scriptId}, hitCount, children:[ids]}], startTime, endTime, samples:[nodeId...], timeDeltas:[µs...] }`. `samples[i]` is the leaf node id of sample *i*; `timeDeltas[i]` is µs since the previous sample. **Line/column are 0-based.** Self time = sum of deltas for samples whose leaf is that node; total time = self + descendants (dedupe recursion!).

```js
// top-cpuprofile.mjs — usage: node top-cpuprofile.mjs file.cpuprofile [N]
import { readFileSync } from 'node:fs';
const [file, nArg = '25'] = process.argv.slice(2);
const p = JSON.parse(readFileSync(file, 'utf8'));
const byId = new Map(p.nodes.map(n => [n.id, n]));
const parent = new Map();
for (const n of p.nodes) for (const c of n.children ?? []) parent.set(c, n.id);
const self = new Map();                       // nodeId -> µs
for (let i = 0; i < p.samples.length; i++)
  self.set(p.samples[i], (self.get(p.samples[i]) ?? 0) + (p.timeDeltas[i] ?? 0));
const key = n => { const f = n.callFrame;
  return `${f.functionName || '(anonymous)'} ${f.url.replace(/^file:\/\//,'')}:${f.lineNumber + 1}:${f.columnNumber + 1}`; };
const selfBy = new Map(), totalBy = new Map();
for (const [id, t] of self) {
  const k = key(byId.get(id)); selfBy.set(k, (selfBy.get(k) ?? 0) + t);
  const seen = new Set();                     // count each function once per stack (recursion)
  for (let cur = id; cur != null; cur = parent.get(cur)) {
    const kk = key(byId.get(cur)); if (seen.has(kk)) continue; seen.add(kk);
    totalBy.set(kk, (totalBy.get(kk) ?? 0) + t);
  }
}
const total = [...self.values()].reduce((a, b) => a + b, 0);
console.log(`total sampled: ${(total/1000).toFixed(1)} ms, samples: ${p.samples.length}`);
console.log('self_ms  self%  total_ms  function');
for (const [k, t] of [...selfBy].sort((a, b) => b[1] - a[1]).slice(0, +nArg))
  console.log(`${(t/1000).toFixed(1).padStart(7)} ${(100*t/total).toFixed(1).padStart(5)}% ${((totalBy.get(k)??0)/1000).toFixed(1).padStart(8)}  ${k}`);
```
Local output for a toy script:
```
total sampled: 130.8 ms, samples: 114
self_ms  self%  total_ms  function
   66.7  51.0%     66.7  strcat .../hot.js:2:16
   44.0  33.6%     44.0  (garbage collector) :0:0
   14.8  11.3%     14.8  (program) :0:0
```
Extensions an agent typically wants: filter out `node:internal/*` and `node_modules` (or aggregate by package), aggregate by URL (file-level), show top callers of a hot function (walk `parent`), diff two profiles by function key (before/after). Use `hitCount` only as a fallback — `timeDeltas` is accurate with variable intervals. Source-mapped TS: the profile has JS positions; map with `source-map`'s `SourceMapConsumer.originalPositionFor` or run with `--enable-source-maps` (doesn't rewrite profiles; mapping must be done offline) — unverified whether DevTools auto-maps loaded `.cpuprofile` files.

### 1.7 Linux `perf` and samply (native + JS mixed stacks)
```bash
# Linux CI / Docker:
perf record -F 999 -g -- node --perf-basic-prof --interpreted-frames-native-stack app.js
perf script > out.perf   # -> FlameGraph stackcollapse-perf.pl / speedscope / Firefox Profiler
# samply (Firefox Profiler UI; works on macOS & Linux):
samply record -- node --perf-prof --perf-basic-prof --interpreted-frames-native-stack app.js
```
- `--perf-basic-prof` writes `/tmp/perf-<pid>.map` (JIT symbol map); `--perf-prof` writes jitdump (`jit-*.dump`) — **both are Linux-only in Node**; on macOS JS frames show as unsymbolized JIT addresses (run in Docker/Linux VM, or use `--cpu-prof` instead). (https://rspack.rs/contribute/development/profiling , https://github.com/mstange/samply/issues/417)
- `--perf-basic-prof-only-functions` reduces map size; maps grow unbounded on long runs.
- Use perf/samply when time is in **native addons, libuv, GC, or Rust/N-API** (Rspack, SWC, esbuild-wasm, Prisma engines). On macOS for native binaries: `samply record` or `xcrun xctrace record --template 'Time Profiler' --launch -- <binary>`.

---

## 2. Node.js memory

### 2.1 Quick telemetry
```js
const m = process.memoryUsage();   // { rss, heapTotal, heapUsed, external, arrayBuffers }
process.memoryUsage.rss();         // cheap
v8.getHeapStatistics();            // heap_size_limit, used_heap_size, ...
v8.getHeapSpaceStatistics();       // per-space (new_space, old_space, large_object_space...)
```
`rss` growing while `heapUsed` is flat → native/Buffer/ArrayBuffer leak (`external`, `arrayBuffers`) or allocator fragmentation, not a JS-object leak.

### 2.2 GC tracing
```bash
node --trace-gc app.js                  # one line per GC (Scavenge / Mark-Compact, ms, MB before->after)
node --trace-gc --trace-gc-verbose app.js
node --expose-gc app.js                 # enables global.gc() for benchmarks/tests
```
Programmatic: `new PerformanceObserver(l => ...).observe({ entryTypes: ['gc'] })` from `node:perf_hooks` (entry.detail.kind = major/minor/incremental/weakcb).

### 2.3 Sampling heap profiler (allocation hot spots — low overhead)
```bash
node --heap-prof --heap-prof-dir=./prof --heap-prof-interval=65536 app.js   # -> *.heapprofile (default interval 512 KiB)
```
`.heapprofile` = tree of `{callFrame, selfSize, children}` + `samples` — parse like §1.6 summing `selfSize` to get top allocating functions. Load into DevTools Memory tab. It shows **allocation sites still live at the end** (sampling), not total churn.

### 2.4 Heap snapshots (retainers / leaks)
```bash
node --heapsnapshot-signal=SIGUSR2 app.js & kill -USR2 $!            # on-demand
node --max-old-space-size=200 --heapsnapshot-near-heap-limit=2 app.js # auto before OOM
```
```js
import v8 from 'node:v8';
v8.writeHeapSnapshot();                 // returns filename; blocks the event loop; needs ~2x heap memory
v8.setHeapSnapshotNearHeapLimit(2);
```
Gotchas: snapshotting a 2 GB heap can take tens of seconds and double memory — risky in prod containers (OOM-kill). Strings and closures dominate; `(system)`/`(compiled code)` noise is normal.

**Three-snapshot leak workflow** (agent-friendly): warm up → snapshot A → run the suspected operation N times → force `gc()` → snapshot B → run N more → snapshot C. Objects allocated between A–B *and still alive in C*, whose count scales with N, are leak candidates. Automate with **memlab**:
```bash
npx memlab find-leaks --snapshot-dir ./snaps      # baseline/target/final snapshots (Node or browser)
npx memlab analyze unbound-object --snapshot-dir ./snaps
npx memlab analyze unbound-collection --snapshot-dir ./snaps  # Maps/Sets/arrays that only grow
npx memlab view-heap --snapshot ./snaps/s3.heapsnapshot
npx memlab trace --node-id 12345                   # retainer path
```
memlab ships `AI.md` (agent guidance) and **`@memlab/mcp-server`** (36 heap-query tools) — https://github.com/facebook/memlab/blob/main/AI.md . For browsers, memlab drives Puppeteer scenarios (`memlab run --scenario s.js`). Classic leak roots: module-level caches/Maps without eviction, listeners never removed (`EventEmitter` "MaxListenersExceededWarning" is a hint), closures capturing large scopes, unbounded promise queues, timers, AsyncLocalStorage contexts held by long-lived resources.

### 2.5 Heap limits
- `--max-old-space-size=4096` (MiB). In containers prefer **`--max-old-space-size-percentage=75`** (present in Node 24.20 `node --help` locally; added via nodejs/node PR #59631, 2025 — exact first version unverified).
- `--max-heap-size` reported added in 25.9.0 (backport to 24.15 claimed; **not** listed in local Node 24.20 `--help` → unverified for 24.x). https://nodejs.org/en/blog/release/v25.9.0
- `NODE_OPTIONS=--max-old-space-size=…` is the common fix for `tsc`/webpack OOMs in CI; a sudden need for it is a perf regression signal.

---

## 3. Event loop, async, and JIT/deopt analysis

### 3.1 Event loop delay and utilization
```js
import { monitorEventLoopDelay, performance } from 'node:perf_hooks';
const h = monitorEventLoopDelay({ resolution: 10 }); h.enable();
setInterval(() => {
  console.log({ p50: h.percentile(50)/1e6, p99: h.percentile(99)/1e6, max: h.max/1e6 }); // ms
  h.reset();
}, 5000).unref();
let last = performance.eventLoopUtilization();
setInterval(() => { const cur = performance.eventLoopUtilization(last); last = performance.eventLoopUtilization();
  console.log('ELU', cur.utilization.toFixed(2)); }, 5000).unref();
```
ELU near 1.0 = CPU-bound main thread (profile it); high latency with low ELU = waiting on I/O / downstream. ELU is also available per worker (`worker.performance.eventLoopUtilization()`).
Blocked-loop detection in dev: `node --trace-sync-io app.js` (warns on sync I/O after first tick).

### 3.2 async_hooks / AsyncLocalStorage / diagnostics_channel
- `async_hooks.createHook` is **low-level and expensive** (Node docs discourage it); use only for debugging.
- `AsyncLocalStorage` is the supported context API (implemented on `AsyncContextFrame` in recent Node, much cheaper than the older hook-based version).
- `node:diagnostics_channel` + `TracingChannel` is how undici (`fetch`), `http`, and many libraries publish events (`undici:request:create`, `http.client.request.start`, …) — subscribe to time requests without monkey patching; this is what OpenTelemetry instrumentations increasingly use.
- `performance.mark/measure` + `PerformanceObserver` for user timings; `perf_hooks.createHistogram()` for custom latency histograms; `performance.timerify(fn)` for function timing.

### 3.3 V8 optimization / deoptimization
Tiers in current V8: Ignition (interpreter) → Sparkplug (baseline) → **Maglev** (mid-tier optimizer) → TurboFan (top tier; **Turbolev** = Maglev-graph front end for Turboshaft is being rolled out). (https://www.thenodebook.com/node-arch/v8-engine-intro)
```bash
node --trace-opt --trace-deopt app.js 2>&1 | grep -E 'deoptimiz|bailout' | sort | uniq -c | sort -rn | head
node --trace-deopt-verbose app.js     # reason + bytecode offset, very noisy
node --trace-ic app.js                # inline cache state log (for deoptexplorer)
```
Native syntax for focused experiments (never in production code):
```js
// node --allow-natives-syntax probe.js
function f(o) { return o.x + 1; }
%PrepareFunctionForOptimization(f);
f({x:1}); f({x:2});
%OptimizeFunctionOnNextCall(f);
f({x:3});
console.log(%GetOptimizationStatus(f).toString(2)); // bit flags; bit 4 (16) = TurboFan-optimized (bit meanings change across V8 versions)
f({x:1, y:2}); // new hidden class -> may deopt
```
- **Deopt Explorer** (VS Code, microsoft/deoptexplorer-vscode; still released, e.g. v1.1.2): visualizes `--log-deopt --log-ic --log-maps --log-maps-details --log-code --log-source-code --prof` logs; ships `dexnode` wrapper: `npx dexnode app.js` → open the log in VS Code. (https://devblogs.microsoft.com/typescript/introducing-deopt-explorer/)
- Heuristic: repeated deopts of the same function ("deopt loop") or **megamorphic** ICs (>4 shapes at one property access) in a hot function are worth fixing; one-off deopts during warmup are not.

---

## 4. Bun and Deno

### 4.1 Bun (JavaScriptCore) [verified locally, Bun 1.3.14]
```bash
bun --cpu-prof script.ts                      # .cpuprofile (Chrome format), 1 ms sampling
bun --cpu-prof-md script.ts                   # Markdown report: summary, hot functions by self time, call tree, callers, per-file
bun --cpu-prof --cpu-prof-md --cpu-prof-dir=prof --cpu-prof-name=run.cpuprofile script.ts
bun --heap-prof script.ts                     # heap snapshot/profile on exit
bun --heap-prof-md script.ts                  # Markdown: top 50 types by retained size, retainer chains, grep hints
bun --inspect script.ts                       # debug.bun.sh web inspector (WebKit)
```
```js
import { heapStats, generateHeapSnapshot } from 'bun:jsc';
heapStats();                                   // object type counts, heap size
await Bun.write('h.json', JSON.stringify(generateHeapSnapshot()));  // open in Safari Web Inspector (JSC format, not V8)
Bun.gc(true); Bun.nanoseconds();
```
- `--cpu-prof-md` is the most LLM-ready profiler output in the ecosystem — prefer it under Bun. (https://bun.com/docs/project/benchmarking)
- Gotcha observed locally: in the Markdown "Total" column, a **recursive function's total time was over-counted** (fib showed 100% / 198 ms of a 130 ms run). Trust Self%, sanity-check Total% for recursion.
- JSC ≠ V8: deopt behaviour, GC attribution, and relative speeds differ. Profile on the runtime you ship. Bun heap snapshots are JSC format (Safari), not V8 `.heapsnapshot`.
- `BUN_JSC_*` env vars expose JSC options (e.g. JIT tracing) — specifics unverified.

### 4.2 Deno (V8)
```bash
deno run --cpu-prof --cpu-prof-dir=prof main.ts
deno run --cpu-prof --cpu-prof-md --cpu-prof-flamegraph main.ts   # + Markdown report + SVG flamegraph
deno run --inspect-brk main.ts                                       # chrome://inspect
deno bench                     # runs *_bench.ts / *.bench.ts
deno bench --json --filter parse
```
```ts
Deno.bench({ name: 'parse', group: 'json', baseline: true }, () => { JSON.parse(s); });
Deno.bench('with setup', (b) => { const data = setup(); b.start(); work(data); b.end(); });
```
Output columns: `time/iter (avg)`, `iter/s`, `(min … max)`, `p75 p99 p995`. (https://docs.deno.com/runtime/reference/cli/bench/). Support for `--cpu-prof` under `deno test`/`deno bench` is unverified. Deno also accepts V8 flags via `--v8-flags=--trace-deopt,...`.

---

## 5. Micro/macro benchmarking

### 5.1 Which harness
| Need | Pick | Notes |
|---|---|---|
| Rigorous microbench, cross-runtime (Node/Bun/Deno/browser) | **mitata** | DCE detection (`!` marker), `do_not_optimize`, GC control, computed params, HW counters via `@mitata/counters` (macOS Apple Silicon + Linux) |
| Tiny embeddable / programmatic | **tinybench** 6.x | `Bench` + tasks, `.table()`; powers vitest bench and CodSpeed plugin |
| Already on Vitest | **`vitest bench`** | **API differs between Vitest 4 and 5** (below) |
| Deno | `deno bench` | built in |
| Bun | mitata (Bun's own recommendation) | |
| Whole CLI / process | **hyperfine** | |
| HTTP throughput/latency | **autocannon** (Node), **oha** / bombardier (native, less client-overhead), **k6** 2.x (scenarios, thresholds, TS) | |
| CI regression detection | **CodSpeed** (simulation mode), **Bencher**, github-action-benchmark | |
| Don't | benchmark.js (archived), jsperf-style one-off loops with `Date.now()` | |

### 5.2 mitata
```js
import { bench, group, summary, barplot, run, do_not_optimize } from 'mitata';
summary(() => {
  bench('JSON.parse', () => do_not_optimize(JSON.parse(input)));
  bench('custom', () => do_not_optimize(customParse(input)));
});
bench('alloc', () => Array.from({ length: 1024 })).gc('inner');      // GC before each iteration
bench('new Array($size)', function* (state) {                         // parameterized
  const size = state.get('size'); yield () => new Array(size);
}).range('size', 1, 1024);
bench('a*b', function* () {                                           // computed params defeat loop-invariant hoisting
  yield { [0]() { return Math.random(); }, [1]() { return Math.random(); },
          bench(a, b) { do_not_optimize(a * b); } };
});
await run({ format: 'json' });        // or default pretty; filter: /re/; throw: true
```
Run Node with `node --expose-gc bench.mjs` so mitata can GC between benches (it does GC after warmup by default when available). (https://github.com/evanwashere/mitata)

### 5.3 tinybench
```js
import { Bench } from 'tinybench';
const b = new Bench({ time: 1000, warmupTime: 200 });
b.add('map', () => arr.map(f)).add('for', () => { for (...) ... });
await b.run(); console.table(b.table());
```
Relies on `performance.now()` per iteration batch; no DCE protection — consume results (e.g., assign to a module-level sink).

### 5.4 Vitest bench — version split
**Vitest 4.x (experimental):** top-level `import { bench, describe } from 'vitest'`; `vitest bench --outputJson main.json` then `vitest bench --compare main.json`.
**Vitest 5.x (2026-09-03):** `bench` is a **test-context fixture** inside `*.bench.ts` / `*.benchmark.ts`; `--compare`/`--outputJson` removed:
```ts
import { test, expect } from 'vitest';
test('parsers', async ({ bench }) => {
  const r = await bench.compare(
    bench('JSON.parse', () => JSON.parse(input)),
    bench('custom', () => customParse(input), { writeResult: './bench/custom.json' }),
    bench.from('previous', './bench/custom.json'),           // baseline replay
  );
  expect(r.get('custom')).toBeFasterThan(r.get('JSON.parse'));
});
```
Run with `vitest bench`. Default provider = tinybench. (https://vitest.dev/guide/benchmarking). Exact signature of `writeResult` (per-bench option) and `toBeFasterThan` taken from docs/blog excerpts — verify against the installed version. Known issue: `bench.compare` no longer prints relative scores in 5.0 (vitest-dev/vitest#11148).

### 5.5 hyperfine (CLIs, builds, startup)
```bash
hyperfine --warmup 3 --runs 20 'node dist/cli.js --help' 'bun dist/cli.js --help'
hyperfine --prepare 'rm -rf node_modules/.cache' 'npx tsc -p . --noEmit'
hyperfine -N 'node -e 0'                     # -N/--shell=none removes shell spawn overhead for fast commands
hyperfine --export-json r.json --export-markdown r.md ...
hyperfine -L v 22,24,26 'npx -y node@{v} bench.js'   # parameter list
```

### 5.6 HTTP load
```bash
npx autocannon -c 100 -d 30 -p 10 http://localhost:3000/api   # -p pipelining; reports latency p50..p99, req/s
oha -z 30s -c 100 http://localhost:3000/api
k6 run --vus 100 --duration 30s load.ts                        # k6 ≥1.0 runs .ts natively; thresholds fail the run
```
Gotchas: run the load generator on a **different core set/machine** than the server (or at least note it); autocannon is itself Node and can saturate first — compare with oha. Measure tail latency (p99), not just req/s. Combine with `--cpu-prof` on the server for the "why".

### 5.7 Benchmark pitfalls (JIT/GC) and mitigations
1. **Dead-code elimination**: result unused → V8 may delete the work. Use `do_not_optimize` (mitata) or a global sink; mitata flags suspiciously fast results.
2. **Constant folding / loop-invariant hoisting**: inputs that are literals get folded; use computed params / randomized inputs generated outside the timed region.
3. **Warmup & tier-up**: first ~thousands of calls run in Ignition/Sparkplug; Maglev/TurboFan later. Always warm up; report steady state *and* cold-start separately if startup matters.
4. **Polymorphism bias**: a microbench calling a function with one shape is monomorphic; production may be megamorphic. Feed realistic shape mixes.
5. **Order effects / shared feedback**: benchmarking A then B in one process lets A's type feedback pollute shared helpers. Randomize order or run each case in a fresh process (hyperfine / separate files).
6. **GC noise**: allocation-heavy cases get GC pauses attributed randomly; use `.gc('inner')` or report allocations (heap-prof) alongside time; `--expose-gc`.
7. **Timer resolution**: `performance.now()` is coarse in browsers (cross-origin isolation affects it); batch iterations.
8. **Machine noise**: laptops throttle (Apple Silicon P/E cores, thermal), CI VMs have noisy neighbours (±5–20% typical). Use `nice`, close apps, plug in power; in CI prefer CodSpeed simulation mode or relative comparisons within one job (A/B interleaved), never cross-run absolute ns.
9. **Statistics**: report median + p75/p99 and number of samples; treat under 5% differences as noise unless repeated with confidence intervals.

### 5.8 CI continuous benchmarking
**CodSpeed** (best signal on shared CI): simulation mode (Valgrind-based CPU simulation → instruction/cache-miss counts → under 1% variance claims; **excludes syscalls/I/O**), walltime mode needs CodSpeed macro runners.
```ts
// vitest.config.ts (Vitest 3.2/4.x; Vitest 5 support pending in PR #86)
import codspeedPlugin from '@codspeed/vitest-plugin';
import { defineConfig } from 'vitest/config';
export default defineConfig({ plugins: [codspeedPlugin()] });
```
```yaml
- uses: CodSpeedHQ/action@v5
  with:
    mode: simulation          # "instrumentation" is the deprecated name
    run: npx vitest bench
```
tinybench: `import { withCodSpeed } from '@codspeed/tinybench-plugin'; const bench = withCodSpeed(new Bench());` (≥5.0 requires tinybench ≥4). Locally the plugins are no-ops (normal tinybench timing). (https://codspeed.io/docs/benchmarks/nodejs/vitest)

**Bencher**: `bencher run --adapter js_time "node bench.js"` (parses `console.time` output; also `json` adapter for BMF) with `--branch`, `--testbed`, `--threshold-measure latency --threshold-test t_test --err` to fail PRs. (https://bencher.dev/docs/explanation/adapters/)

**github-action-benchmark**: `tool: benchmarkjs | customSmallerIsBetter | customBiggerIsBetter`, `alert-threshold: '130%'`, `fail-on-alert: true`, stores history in gh-pages. Emit mitata/tinybench JSON → convert to `[{name, unit, value}]` for `customSmallerIsBetter`. (https://github.com/benchmark-action/github-action-benchmark)

---

## 6. TypeScript compiler and build performance

### 6.1 TS ≤ 6 (JS-based tsc) — still relevant for frameworks pinned to TS 6
```bash
npx tsc -p . --noEmit --extendedDiagnostics      # Files, Lines, Identifiers, Types, Instantiations, Memory used, I/O/Parse/Bind/Check/Emit time
npx tsc -p . --noEmit --generateTrace ./ts-trace --incremental false
npx @typescript/analyze-trace ./ts-trace         # hot spots: files/expressions/types with long check time
npx @typescript/analyze-trace ./ts-trace --forceMillis 100 --skipMillis 50   # thresholds (verify flags with --help)
npx tsc --listFilesOnly | wc -l ; npx tsc --explainFiles > why.txt   # why is a file in the program?
node --cpu-prof ./node_modules/typescript/lib/tsc.js -p . --noEmit   # V8 profile of the checker
```
Read `--extendedDiagnostics`: huge `Instantiations` or `Types` count → complex generics/conditional types (often zod/trpc/drizzle/type-level libs, deep `infer` recursion, giant unions). `Files` much larger than expected → leaking `include`, missing `skipLibCheck`, wildcard `types`. `trace.json` loads in `chrome://tracing` / Perfetto; `types.json` maps type ids. (https://github.com/microsoft/TypeScript/wiki/Performance-Tracing)

### 6.2 TS 7 (native Go, `tsc` from `typescript@7`)
- ~10x faster full checks (VS Code: 125.7 s → 10.6 s per Microsoft). Parallelism: `--checkers N` (default 4), `--builders N` (project references), `--singleThreaded` (debug/repro, fair comparison). (https://typescriptpro.com/blog/typescript-version-7-2026-07-08)
- `--extendedDiagnostics` works (Microsoft's Dec 2025 progress post shows `tsgo -b ... --extendedDiagnostics`). (https://devblogs.microsoft.com/typescript/progress-on-typescript-7-december-2025/)
- **`--generateTrace` support in TS 7: unverified.** Native profiling: `--pprofDir <dir>` writes Go pprof CPU+memory profiles → `go tool pprof -top -cum <file>` (https://compassrx.dev/blog/3/fixing-tsgo/ — found a quadratic regression this way). Flag documented by community only → treat as unverified/internal.
- `node --cpu-prof` is **useless** on TS 7 (it's a Go binary); profile with pprof, `samply record`, or Instruments.
- Removed options become hard errors (ES5 target, AMD/UMD/System, `moduleResolution: node10/classic`, `baseUrl`, `esModuleInterop:false`…). No Strada API → typescript-eslint type-aware linting, Vue/Svelte/Astro/Angular tooling may still need `@typescript/typescript6` alongside. Lint time (`typescript-eslint` with `projectService`) often dominates after TS 7 — profile ESLint separately: `TIMING=1 npx eslint .` (per-rule times) and `node --cpu-prof node_modules/eslint/bin/eslint.js .`.

### 6.3 Structural TS speedups (any version)
- **Project references** + `tsc -b` (and `--builders` in TS 7) for monorepos; `composite`, `incremental` + `tsBuildInfoFile` cached in CI.
- **`isolatedDeclarations`** (TS 5.5+): explicit types on exports → `.d.ts` emit without type-checking, parallelizable by other tools (oxc/swc `isolatedDeclarations` transforms).
- `skipLibCheck: true`; narrow `include`/`types`; prefer `interface extends` over big intersections; annotate return types of exported functions; avoid huge unions (>~100k comparisons) and deep recursive conditional types; split giant files.
- Separate **transpile** (esbuild/swc/oxc/Bun/`node --experimental-strip-types`—type stripping is on by default in Node ≥23.6/22.18) from **type-check** (`tsc --noEmit`, run in parallel or in CI only).

### 6.4 Bundlers
- **esbuild**: `--metafile=meta.json` → https://esbuild.github.io/analyze/ ; `--analyze` prints size breakdown. Build time profiling rarely needed.
- **Vite 8 / Rolldown**: build is Rust; slowness usually from JS plugins (each plugin hook crosses the JS boundary). `vite build --debug`, `DEBUG=vite:* `, and `vite --profile` (writes `.cpuprofile` of the Vite Node process; press `p` in dev server to start/stop) — Vite 8 specifics of `--profile` unverified. Use `vite-plugin-inspect` to see per-plugin transform times.
- **Rspack 2**: `RSPACK_PROFILE=OVERVIEW rspack build` → `.rspack-profile-<ts>-<pid>/` trace (open in Perfetto); `RSPACK_PROFILE=ALL` for detail (verify value names); **Rsdoctor** (`RSDOCTOR=true`) for loader/plugin timing + bundle analysis ("AI-friendly build analyzer"). Stop dev server with Ctrl+D so the profile is flushed. (https://rsbuild.rs/guide/debug/build-profiling)
- **webpack 5**: `node --cpu-prof node_modules/webpack/bin/webpack.js`; `ProfilingPlugin` (Chrome trace of plugin hooks); `speed-measure-webpack-plugin` is stale (incompatible with many webpack 5 setups). Usual big wins: persistent cache (`cache: { type: 'filesystem' }`), swc/esbuild-loader instead of babel/ts-loader, `fork-ts-checker` or separate tsc, or migrate to Rspack.

### 6.5 Startup / import cost
```bash
hyperfine -N --warmup 5 'node dist/cli.js --version'
node --cpu-prof --cpu-prof-interval=50 dist/cli.js --version     # profile *startup*; look at compileFunction / require / loadESM
NODE_DEBUG=module node dist/cli.js 2>&1 | wc -l                    # rough count of module resolutions
node --import ./trace-imports.mjs app.js                           # custom: module.register() hook timing each load (unverified recipe)
```
High-leverage fixes: lazy `require`/`await import()` for rarely used subcommands; avoid barrel files (`index.ts` re-exporting everything — kills tree-shaking and loads every module); bundle CLIs into one file; **`module.enableCompileCache()`** or `NODE_COMPILE_CACHE=dir` (Node ≥22.1) caches V8 bytecode across runs; avoid top-level sync work (reading big JSON/config at import). Bun's startup is typically lower; measure with hyperfine instead of assuming.

---

## 7. Frontend / browser performance

### 7.1 Lab: Lighthouse and Lighthouse CI
```bash
npx lighthouse https://localhost:3000 --output=json --output-path=lh.json --only-categories=performance \
  --chrome-flags="--headless=new" --throttling-method=simulate --preset=desktop
jq '.audits["largest-contentful-paint"].numericValue, .categories.performance.score' lh.json
npx @lhci/cli autorun          # uses lighthouserc.{js,json}
```
```js
// lighthouserc.js
module.exports = { ci: {
  collect: { url: ['http://localhost:3000/'], numberOfRuns: 5, startServerCommand: 'npm run start' },
  assert: { preset: 'lighthouse:recommended', assertions: {
    'categories:performance': ['error', { minScore: 0.9, aggregationMethod: 'median-run' }],
    'largest-contentful-paint': ['error', { maxNumericValue: 2500 }],
    'cumulative-layout-shift': ['error', { maxNumericValue: 0.1 }],
    'total-blocking-time': ['warn', { maxNumericValue: 200 }],
    'resource-summary:script:size': ['error', { maxNumericValue: 300000 }],
  } },
  upload: { target: 'temporary-public-storage' } } };
```
Gotchas: Lighthouse is lab-only (no INP — use TBT as proxy); run ≥3–5 times, take median; Lighthouse 13 removed/renamed many audits (e.g. `layout-shifts`→`cls-culprits-insight`, image audits → `image-delivery-insight`) so **assertions referencing removed audit IDs silently disappear** — pin versions and re-check config after upgrades. LHCI is slowly maintained (0.15.1, 2025-06) but works. (https://github.com/GoogleChrome/lighthouse-ci/blob/main/docs/configuration.md)

### 7.2 Field: Core Web Vitals via `web-vitals`
Thresholds (good): **LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1** at p75.
```js
import { onLCP, onINP, onCLS, onTTFB } from 'web-vitals/attribution';   // v5/v6
const send = (m) => navigator.sendBeacon('/rum', JSON.stringify({ name: m.name, value: m.value,
  rating: m.rating, id: m.id, nav: m.navigationType, attr: m.attribution }));
onLCP(send); onINP(send); onCLS(send); onTTFB(send);
```
v5: `onFID` removed; `LCPAttribution.element`→`target`; INP attribution includes LoAF (long animation frame) data (longest script, time buckets). v6: soft-navigation support (SPA route changes), `includeProcessedEventEntries` default false, bfcache tweaks. (https://github.com/GoogleChrome/web-vitals/blob/main/docs/upgrading-to-v5.md). INP diagnosis: `attribution.longestScript`, `inputDelay` vs `processingDuration` vs `presentationDelay` tells you whether to break up other tasks, speed up the handler, or reduce rendering work.

### 7.3 Chrome DevTools Performance panel & trace JSON
- Record → "Save profile" gives trace JSON (`{traceEvents:[...]}` or `.json.gz`). Insights sidebar (LCP breakdown, INP by phase, render-blocking, layout-shift culprits, 3rd-party, forced reflow, DOM size).
- Programmatic parsing: **`@paulirish/trace_engine`** (the DevTools trace engine on npm; explicitly "not for wide consumption", breaking changes possible; needs a `DOMRect` polyfill in Node):
```js
import * as TraceModel from '@paulirish/trace_engine';
const engine = TraceModel.Processor.TraceProcessor.createWithAllHandlers();
await engine.parse(JSON.parse(fs.readFileSync('trace.json')).traceEvents);
// engine.parsedTrace / engine.insights  (property names vary by version — inspect)
```
- Quick DIY: filter `traceEvents` where `name==='RunTask'` and `dur>50000` (µs) for long tasks; `name==='FunctionCall'`/`EvaluateScript` with `args.data.url` for script attribution; `LayoutShift`, `largestContentfulPaint::Candidate`, `EventTiming` for vitals.
- React 19.2+ adds **React Performance Tracks** (Scheduler/Components) to the Performance panel in dev/profiling builds (React 19.2 release notes; verify on your version).

### 7.4 Automated capture with Puppeteer / Playwright
```js
// Puppeteer
await page.tracing.start({ path: 'trace.json', screenshots: true,
  categories: ['devtools.timeline', 'disabled-by-default-devtools.timeline', 'v8.execute', 'blink.user_timing', 'loading'] });
await page.goto(url, { waitUntil: 'networkidle0' });
await page.tracing.stop();
const m = await page.metrics();      // JSHeapUsedSize, ScriptDuration, LayoutDuration, TaskDuration...
// CPU throttle to emulate mid-tier mobile:
const cdp = await page.createCDPSession(); await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
// JS CPU profile only: cdp.send('Profiler.enable'); cdp.send('Profiler.start'); ... ('Profiler.stop') -> .cpuprofile (parse with §1.6)
```
```js
// Playwright (Chromium only)
await browser.startTracing(page, { path: 'trace.json', screenshots: true, categories: ['devtools.timeline'] });
await page.goto(url); await browser.stopTracing();
// Playwright's context.tracing (trace.zip / Trace Viewer) is for debugging tests, NOT a perf trace.
```
Measure INP-like latency in automation via `PerformanceObserver({type:'event', durationThreshold:16})` in the page (`page.evaluate`) after scripted clicks. Use fixed CPU throttle + network emulation and median of N runs.

### 7.5 Chrome DevTools MCP (agent-driven traces) [verified status]
Install for Claude Code: `claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest` (README also shows a `claude mcp add` form; exact syntax per README). Useful flags: `--headless`, `--isolated` (temp profile), `--channel=canary|beta`, `--browserUrl=http://127.0.0.1:9222` (attach to your Chrome), `--slim`, **`--no-performance-crux`** (otherwise trace URLs are sent to Google's CrUX API for field data), `--no-usage-statistics` / `CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS`. Tools: `performance_start_trace {reload, autoStop, filePath}`, `performance_stop_trace`, `performance_analyze_insight` (drill into LCP breakdown, render-blocking, etc.), `emulate` (CPU throttle `cpuThrottlingRate`, network presets Slow 3G…Fast 4G, viewport, UA), `lighthouse_audit`, heap tools (`take_heapsnapshot`, `compare_heapsnapshots`, `get_heapsnapshot_retaining_paths`, `get_heapsnapshot_dominators`, `query_heapsnapshot_objects`, `analyze_heapsnapshot_contexts`), `evaluate_script`, console/network listing. v1.10.0 (2026-09-23) added chunked trace parsing for large traces. (https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/tool-reference.md , https://developer.chrome.com/blog/chrome-devtools-mcp)
Agent loop: start dev server → `emulate` (CPU 4x, Slow 4G) → `performance_start_trace {reload:true, autoStop:true, filePath:'trace.json.gz'}` → read insights → `performance_analyze_insight` on the worst → change code → repeat with same emulation → compare LCP/CLS/TBT numerically; save traces as artifacts.

### 7.6 React-specific
- **React DevTools Profiler** (commit flamegraph, "why did this render?" setting). Programmatic: `<Profiler id="x" onRender={(id, phase, actualDuration, baseDuration, startTime, commitTime) => ...}>` (needs profiling build: `react-dom/profiling` alias in prod).
- **React Compiler 1.0** (`babel-plugin-react-compiler`; integrated in Vite/Next/Expo templates; lint rules in `eslint-plugin-react-hooks` recommended preset) auto-memoizes; reduces need for manual `useMemo/useCallback/memo`. Meta reports up to 12% faster initial loads and >2.5x faster interactions in Quest Store. Verify with Profiler before/after; bail-outs are reported by the lint rules. (https://react.dev/blog/2025/10/07/react-compiler-1)
- **react-scan** (drop-in render-highlighting overlay; `npx react-scan@latest http://localhost:3000`) — the 2025–26 default for spotting wasted renders; **why-did-you-render** still maintained, supports React 19 (needs automatic JSX runtime) and logs prop/state diffs. (https://github.com/welldone-software/why-did-you-render)
- Common React wins: virtualize long lists (TanStack Virtual), move state down / split contexts (context value identity changes re-render all consumers), `useTransition`/`useDeferredValue` for INP, avoid creating components inside render, stable `key`s, code-split routes (`lazy`).

### 7.7 Bundle analysis and budgets
```bash
npx source-map-explorer 'dist/assets/*.js' --json > sme.json      # needs sourcemaps; byte attribution per source file
npx vite-bundle-visualizer   # or rollup-plugin-visualizer({ template: 'treemap'|'sunburst'|'raw-data', gzipSize: true, brotliSize: true })
npx webpack-bundle-analyzer dist/stats.json          # webpack --profile --json > stats.json
npx esbuild ... --metafile=meta.json --analyze
```
`rollup-plugin-visualizer` `template: 'raw-data'` (JSON) or `'list'` is the agent-readable variant. **size-limit** for budgets:
```json
// package.json
"size-limit": [{ "path": "dist/index.js", "limit": "12 kB" }, { "path": "dist/index.js", "import": "{ parse }", "limit": "3 kB" }]
```
`npx size-limit` (brotli by default; `--json` for machine output; `--why` opens the analyzer; optional `@size-limit/time` estimates execution time in headless Chrome). CI: `andresz1/size-limit-action@v1` comments diffs on PRs and fails on budget breach. (https://github.com/ai/size-limit)

---

## 8. JS/TS performance anti-patterns and high-leverage fixes

Ordered roughly by how often they show up in real profiles (algorithmic & I/O issues beat micro-tuning).

| # | Anti-pattern | Symptom in profile | Fix |
|---|---|---|---|
| 1 | **Sequential awaits** of independent work (`for … await fetch()`) | low CPU, long wall time, idle loop | `Promise.all` / `Promise.allSettled`; bounded concurrency (`p-limit`) to avoid overload |
| 2 | **O(n²) lookups**: `arr.find/includes/indexOf` inside loops, `filter` then `find` | a hot `find`/`includes` frame | build a `Map`/`Set` index once |
| 3 | **Spreading/concat in loops / reducers** (`acc = {...acc, [k]: v}`, `arr = [...arr, x]`) | high `(garbage collector)`, quadratic time | mutate a local accumulator, `push`, `Object.fromEntries` once |
| 4 | **Sync fs/crypto/zlib in hot paths** (`readFileSync`, `execSync`, `pbkdf2Sync`) on servers | event-loop delay spikes, `--trace-sync-io` warnings | async APIs, cache results, move CPU work to `worker_threads` (Piscina pool) |
| 5 | **Megamorphic call sites / unstable hidden classes**: objects built with different property orders, adding props after construction, `delete obj.prop`, mixing types in one field | deopt traces, `--trace-ic` megamorphic | initialize all fields in constructor/literal in the same order; set to `undefined` instead of `delete`; separate code paths per shape; classes over ad-hoc objects in hot code |
| 6 | **Holey / mixed-element arrays**: `new Array(n)` then fill out of order, writing past length, mixing ints/doubles/objects | slower element access, elements-kind transitions | `Array.from({length:n}, …)` or push sequentially; TypedArrays for numeric data |
| 7 | **JSON round-trips**: `JSON.parse(JSON.stringify(x))` for cloning, re-parsing big configs per request | `JSON.parse`/`stringify` self time | parse once and cache; `structuredClone` for real deep copies (handles Map/Date/cycles, but is *not* faster than hand-written copies for plain small objects — measure); for large payloads consider streaming parsers; `JSON.parse` of a large string literal is faster than an equivalent JS object literal for cold load (V8 guidance) |
| 8 | **Catastrophic regex backtracking** (`(a+)+$`, nested quantifiers on user input) | single huge `RegExp` frame, ReDoS | rewrite to linear patterns, anchor, limit input length; test with `safe-regex2`/`recheck`; V8 `--enable-experimental-regexp-engine` (linear) for `/.../l` — experimental |
| 9 | **String building** with repeated `+=` across huge strings then indexing | GC + flattening costs (rope flattening) | `+=` is fine for moderate sizes (V8 ropes); for very large outputs push to an array + `join`, or stream; avoid `str.split('')` char loops |
| 10 | **Closures / allocations per call in hot loops** (`arr.map(x => …).filter(…).reduce(…)` chains on large arrays, creating objects for return tuples) | GC share high, many small frames | fuse into one loop for hot paths; reuse buffers; but keep readable code elsewhere |
| 11 | **Object as hash map** with dynamic/numeric-ish keys, frequent add/delete | dictionary-mode objects | `Map` for dynamic keys and frequent mutation; plain objects for fixed-shape records |
| 12 | **Unbounded caches / listeners** | rising heap, long GC | LRU (`lru-cache`), `WeakMap`/`WeakRef`, remove listeners, `AbortSignal` cleanup |
| 13 | **Logging/serialization in hot path** (`console.log` sync to TTY/file, pretty printers) | `writeSync`/`util.inspect` frames | structured async loggers (pino), log level guards |
| 14 | **try/catch & `arguments`**: historically deopting; **no longer an issue** in TurboFan-era V8 | — | don't "fix" these based on old blog posts |
| 15 | **Buffer/string conversions** (`Buffer.toString()` then `Buffer.from()` repeatedly), `TextEncoder` per call | allocation | keep data as Buffer/Uint8Array; reuse encoders |
| 16 | **Barrel files & eager imports** (startup) | `compileFunction`, module loading frames | direct imports, lazy `import()`, bundle, compile cache |
| 17 | **CPU-bound work on main thread** (image, crypto, parsing, diffing) | ELU≈1, latency for everyone | `worker_threads` (pool, transfer `ArrayBuffer`s; `SharedArrayBuffer`+`Atomics` for heavy sharing); in browser: Web Workers / `scheduler.yield()` to keep INP low |
| 18 | **WASM** | — | worth it for tight numeric/codec/parsing kernels (Rust/Zig/AssemblyScript); boundary crossings (string marshalling) can erase gains — batch data, measure. N-API native addons (napi-rs) for heavier work |
| 19 | **Frontend**: layout thrashing (read `offsetHeight` after writes in a loop), giant DOM, unvirtualized lists, render-blocking scripts, unoptimized LCP image (lazy-loaded hero, no `fetchpriority="high"`), layout shifts from un-sized images/ads/fonts | forced reflow insight, long tasks, CLS culprits | batch reads/writes, `content-visibility: auto`, virtualization, `defer`/`type=module`, preload LCP image, `width/height`/`aspect-ratio`, `font-display` + size-adjust |

Sources for V8-specific advice: https://v8.dev/blog (elements kinds, fast properties, cost of JS), https://www.thenodebook.com/node-arch/v8-engine-intro . Always confirm a hypothesis with a profile + benchmark; several "classic" tips (try/catch, `arguments`, forEach vs for) are obsolete or negligible on modern V8.

---

## 9. LLM/agent-driven performance optimization: research and lessons (2025–2026)

Key findings (mostly Python/C/Java benchmarks; no major JS-specific agent-perf benchmark found — JS-specific evidence is unverified/sparse):
- **SWE-fficiency** (Nov 2025, ICML 2026; 498 tasks, numpy/pandas etc.): agents reach **under 0.23x of expert speedup** on average; **>68% of expert gains are in functions the agent never edits** (mislocalization); agents favour shortcuts (identity checks, early exits, memoization) over restructuring; 15–45% of patches break unit tests; agents stop early (30–50 turns of a 100 cap). (https://arxiv.org/html/2511.06090v1)
- **PerfAgent** (Jul 2026): profiler-guided, verifier-in-the-loop agent doubled expert-matching rate (GSO 19.6%→39.2%; SWE-fficiency-Lite 26%→74%) vs OpenHands baseline, beating best-of-5 at lower cost — **profiles, not timing alone, drive success**. (https://arxiv.org/abs/2607.19653)
- **PERFOPT-Bench** (Jul 2026, C codebases): agents **game evaluators** (specialize to visible workloads, measurement-facing shortcuts); restarting with an externalized optimization summary recovered 1.02–2.48x more speedup → long tasks benefit from written handoff notes. (https://arxiv.org/html/2607.07744)
- **"Are Performance-Optimization Benchmarks Reliably Measuring Coding Agents?"** (Jul 2026): measurement noise and gaming make many reported speedups unreliable; recommends repeated runs and statistical validation. (https://arxiv.org/pdf/2607.01211)
- **"Do AI Models Dream of Faster Code?"** (Oct 2025, Java/JMH): LLMs often produce working speedups but with **extreme run-to-run volatility**, and struggle to find hotspots unaided. (https://arxiv.org/abs/2510.15494)
- **LLMs for DOM-level web perf issues** (Jan 2026): 9 LLMs fixed SEO/a11y issues reliably, performance-critical DOM changes mixed (best ~47–49% audit-incidence reduction), and **most models introduced visual instability (CLS)**. (https://arxiv.org/abs/2601.05502)
- Also: SWE-Perf (140 instances, 2025) https://arxiv.org/pdf/2507.12415 , GSO https://arxiv.org/pdf/2505.23671 .
- Tooling trend: runtimes and tools now emit **LLM-friendly profiles** — Bun `--cpu-prof-md`/`--heap-prof-md`, Deno `--cpu-prof-md`, memlab MCP + AI.md, Chrome DevTools MCP insights, Rsdoctor ("AI-friendly build analyzer").

**Lessons encoded as agent rules**
1. **Measure first, localize with a profiler** (top self-time + callers), never optimize by reading code alone.
2. **Fix the workload and the harness before editing**: a reproducible benchmark/CLI command + correctness tests, kept separate (SWE-fficiency's separation of correctness vs perf workloads).
3. **Baseline N≥5 runs**, report median and spread, re-run after the change in the same environment; interleave A/B when possible. Treat under 5% as noise unless statistically supported.
4. **Prefer algorithmic/structural fixes** (indexes, batching, avoiding repeated work, concurrency) over micro-tweaks; reject "special-case the benchmark input" changes.
5. **Guard correctness**: run full tests; for frontend, check CLS/visual regressions after "perf" changes.
6. **Don't stop at the first win**: re-profile after each change — the hot spot moves.
7. **Record evidence** (profiles, before/after numbers, tool versions) in the PR; leave a short summary so a later session can continue.

---

## 10. Recommended default playbook per scenario (agent cheat sheet)

| Scenario | Default commands |
|---|---|
| "This Node script/CLI is slow" | `hyperfine --warmup 2 '<cmd>'` → `node --cpu-prof --cpu-prof-dir=prof <cmd>` → `node top-cpuprofile.mjs prof/*.cpuprofile 30` → fix → hyperfine again |
| Slow Node server endpoint | `autocannon`/`oha` against endpoint while server runs with `--cpu-prof` (exit via SIGINT handler) or inspector start/stop; watch `monitorEventLoopDelay` p99 and ELU |
| Memory growth / OOM | `--trace-gc` + `process.memoryUsage()` trend → `--heap-prof` for allocation sites → 3 heap snapshots + `memlab find-leaks` / `analyze unbound-collection` |
| Native addon / Rust tool slow | Linux: `perf record -g` / `samply record` with `--perf-basic-prof`; macOS: samply or `xctrace` |
| Microbenchmark a function | mitata (`do_not_optimize`, `node --expose-gc`), fresh process per variant for sensitive comparisons |
| Benchmarks in CI | CodSpeed `mode: simulation` (vitest ≤4 / tinybench) or Bencher/github-action-benchmark with relative thresholds |
| Bun / Deno code | `bun --cpu-prof-md` / `deno run --cpu-prof --cpu-prof-md`; `deno bench`; mitata |
| tsc slow | TS6: `--extendedDiagnostics` → `--generateTrace` + `@typescript/analyze-trace`; TS7: `--extendedDiagnostics`, `--singleThreaded` for repro, `--pprofDir` (unverified) |
| Build slow | Vite: `vite build --debug`/`--profile`, check JS plugins; Rspack: `RSPACK_PROFILE=OVERVIEW` + Rsdoctor; webpack: `--cpu-prof` + filesystem cache |
| Page load / CWV | Chrome DevTools MCP trace with emulation, or Lighthouse JSON (median of 5); LHCI assertions + size-limit in CI; web-vitals v6 with attribution for field |
| React jank | React DevTools Profiler / react-scan → React Compiler, state colocation, virtualization, `useTransition` |
