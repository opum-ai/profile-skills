# Profiling browser pages and frontends

Thresholds for "good" at the 75th percentile: **LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1**.
- **INP** exists only in the field, from real interactions. In the lab, use TBT and the
  latency of scripted interactions as proxies.
- **Lab numbers need fixed CPU and network emulation and a median of ≥3–5 runs.**
- Lighthouse 13 renamed or removed many audits (they became "insights"). Assertions on old
  audit IDs disappear silently, so pin versions.

## Contents
1. Capture a trace (bundled script)
2. Read the trace
3. Interactions and INP
4. Lighthouse / LHCI
5. Chrome DevTools MCP
6. React and frameworks
7. Bundles
8. Common causes by symptom

## 1. Capture a trace

```bash
# needs Playwright where you run it (npm i -D playwright); falls back to installed Chrome
node ${CLAUDE_SKILL_DIR}/scripts/browser_trace.mjs http://localhost:5173/ \
  --out .perf/<c>/baseline --runs 3 --cpu 4 --network fast4g [--interact .perf/<c>/interact.mjs] [--mobile]
python3 $PK hotspots .perf/<c>/baseline/run-1.trace.json --top 15
```
- Each run writes a Chrome trace (V8 CPU samples plus main-thread events), plus
  `metrics.json` with the median TTFB, FCP, LCP, CLS, TBT, long tasks, max interaction,
  DOM nodes, heap and transfer kB.
- `metrics.flat.json` (`web.lcp_ms`, …) feeds `perfkit gate` budgets.
- `perfkit hotspots` on a trace prints:
  - the JS frames by self time;
  - **main-thread totals by event** (`Layout`, `UpdateLayoutTree`, `EvaluateScript`,
    `FunctionCall`, `Paint`);
  - the **long-task count and total blocking time**.
- Serve a **production build** (`vite build && vite preview`, `next build && next start`).
  Dev servers add HMR, unminified code and React dev checks that distort everything.
- Playwright's `context.tracing` (trace.zip) is for debugging tests. It is not a
  performance trace. The script uses `browser.startTracing` (Chromium only).

Puppeteer equivalent:
```js
await page.tracing.start({ path: 'trace.json', categories: ['devtools.timeline', 'disabled-by-default-devtools.timeline', 'v8.execute', 'disabled-by-default-v8.cpu_profiler'] });
```

## 2. Read the trace

- **`Layout` / `UpdateLayoutTree` with huge counts** (thousands per interaction) is **layout
  thrashing**: reading geometry (`offsetWidth`, `getBoundingClientRect`, `scrollTop`) after
  a style write, in a loop.
  - Fix: batch all reads, then all writes. Use `requestAnimationFrame`, or CSS instead of JS
    measurement.
- **`EvaluateScript` / `ParseHTML` / compile in long tasks during load** means too much JS on
  the critical path.
  - Fix: code-split, `defer` / `type=module`, drop unused dependencies, lazy routes.
- **One JS frame dominating self time inside a long task** means an algorithmic or work
  problem in that function. Apply perf-optimize as usual.
- **`Paint` / `Composite` heavy:** large layers, box-shadow or filter animations, a huge DOM.
  Fix with `content-visibility: auto`, virtualized lists, and by animating
  transform/opacity only.
- **LCP late but the main thread idle** is a network or priority problem:
  - a lazy-loaded hero image;
  - a missing `fetchpriority="high"` or preload;
  - render-blocking CSS or fonts;
  - slow TTFB.
- **CLS:** images or ads without dimensions, injected banners, font swaps. Fix with
  `width`/`height`/`aspect-ratio` and `font-display` with size-adjust.

## 3. Interactions and INP

An `--interact` module drives real input after load:
```js
// .perf/<c>/interact.mjs
export default async function (page) {
  await page.click('#sort');            // each click is an interaction with an Event Timing entry
  await page.fill('#search', 'abc');
  await page.keyboard.press('Enter');
}
```
- `maxInteraction` is the worst interaction duration, from input to the next paint. It is the
  INP proxy.
- `interactionBlocking` is the long-task time during interactions.
- The trace shows *which* handler ran.
- An INP breakdown needs field attribution (web-vitals v6, `onINP` with attribution):
  - **input delay:** other tasks were busy, so break them up with `scheduler.yield()`;
  - **processing:** the handler is slow;
  - **presentation delay:** rendering work after the handler, such as a giant re-render or
    layout.

## 4. Lighthouse / LHCI

```bash
npx lighthouse http://localhost:4173/ --output=json --output-path=.perf/<c>/lh.json --only-categories=performance \
  --chrome-flags="--headless=new" --throttling-method=simulate
jq '.audits["largest-contentful-paint"].numericValue, .audits["total-blocking-time"].numericValue, .categories.performance.score' .perf/<c>/lh.json
```
Run it 3–5 times and take the median. For budgets in CI see perf-ci
(`references/web-budgets.md`).

## 5. Chrome DevTools MCP (agent-driven, interactive)

If the `chrome-devtools` MCP server is configured
(`claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest --no-performance-crux`):
1. `emulate` with CPU 4× and a network preset.
2. `performance_start_trace {reload: true, autoStop: true}`.
3. Read the insights, and drill in with `performance_analyze_insight`.
4. Change the code, repeat with the same emulation, and compare the numbers.

The heap tools (`take_heapsnapshot`, `compare_heapsnapshots`) help with leaks.

Pass `--no-performance-crux`, or trace URLs are sent to Google's CrUX API. The bundled
script works without MCP and leaves files you can cite.

## 6. React and frameworks

- **React Profiler:**
  - `<Profiler onRender>` needs a profiling build in prod (`react-dom/profiling`);
  - React DevTools' "why did this render";
  - `npx react-scan@latest http://localhost:3000` highlights wasted renders;
  - React 19.2+ adds Performance-panel tracks.
- **Common wins:**
  - virtualize long lists (TanStack Virtual);
  - move state down, and split contexts (a new context value re-renders every consumer);
  - `useTransition` / `useDeferredValue` for INP;
  - stable keys;
  - no component definitions inside render;
  - React Compiler 1.0 for auto-memoization (verify its bail-outs with the lint rules).
- **Next.js / Vite:** check the route-level JS size in build output, lazy routes,
  `next/image` / responsive images, and the font strategy.

## 7. Bundles

```bash
npx vite-bundle-visualizer             # or rollup-plugin-visualizer template 'raw-data' (JSON) / 'list'
npx source-map-explorer 'dist/assets/*.js' --json > .perf/<c>/sme.json
npx esbuild src/main.ts --bundle --metafile=.perf/<c>/meta.json --outfile=/dev/null && npx esbuild --analyze=verbose ...
npx size-limit --json                  # if configured; budgets in perf-ci
```
Look for:
- duplicate copies of a library;
- the whole of lodash or moment, or icon packs imported through barrels;
- polyfills for targets you don't support;
- JSON or locale data bundled into JS;
- a large dependency used for one function.

## 8. Common causes by symptom

| Symptom | Usual cause | Fix |
|---|---|---|
| high TBT, long `EvaluateScript` | too much JS at load | code-split, defer, remove deps |
| thousands of `Layout` events in one task | read-after-write in a loop | batch reads/writes, CSS |
| slow click/typing | heavy handler, sync re-render of a big list | memoize/virtualize, `useTransition`, worker, `scheduler.yield()` |
| LCP late, CPU idle | hero image lazy/low priority, blocking CSS/fonts, TTFB | preload, `fetchpriority`, inline critical CSS, cache/CDN |
| CLS | unsized media, injected UI, fonts | reserve space, `aspect-ratio`, font metrics override |
| memory grows per navigation | listeners/timers/observers not cleaned, caches | effect cleanups, AbortController, WeakMap; memlab |
