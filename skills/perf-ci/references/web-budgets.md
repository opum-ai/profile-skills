# Web performance budgets

## Lab vitals with the bundled tracer

```bash
npm run build && (npm run preview -- --port 4173 &) && sleep 3
node tools/perfkit/browser_trace.mjs http://localhost:4173/ --runs 5 --cpu 4 --network fast4g --out perf-ci/web
perfkit gate --policy perf-policy.toml --metrics perf-ci/web/metrics.flat.json ...
```
`metrics.flat.json` provides `web.lcp_ms`, `web.fcp_ms`, `web.cls`, `web.tbt_ms`,
`web.max_interaction_ms`, `web.transfer_kb` and `web.dom_nodes` (medians), for use in
`[[budget]]`.
- Lab numbers vary a lot between runners. Use generous budgets (about 20% above the
  measured median), 5 runs, a fixed CPU throttle, and mark budgets `required = false` until
  you have measured their noise.
- **INP needs interactions.** Add `--interact` with a module that clicks and types through
  the critical flows, then budget `web.max_interaction_ms`.

## Lighthouse CI

`assets/lighthouserc.json` contains the median-run assertions for performance score, LCP,
CLS, TBT and script size.
```bash
npx @lhci/cli autorun --config=lighthouserc.json
```
- Lighthouse 13 renamed or removed audits. An assertion on a removed audit ID disappears
  silently, so pin the LHCI and Lighthouse versions and re-check assertions after upgrades.
- Lighthouse has no INP; TBT is its proxy.
- LHCI is slowly maintained (0.15.x) but works. Upload to the `filesystem` target to keep
  artifacts private.

## Bundle size (deterministic)

```json
// package.json
"size-limit": [
  { "path": "dist/assets/index-*.js", "limit": "180 kB" },
  { "path": "dist/index.js", "import": "{ parse }", "limit": "3 kB" }
]
```
- Run `npx size-limit --json` (brotli by default).
- `andresz1/size-limit-action@v1` comments the diff on PRs.
- Or skip the dependency: write a `[[metric]]` that sums the gzip size of `dist/assets/*.js`
  and budget it.

## Field data (the truth)

Lab budgets catch regressions. Field data says whether users are affected.

```js
import { onLCP, onINP, onCLS } from 'web-vitals/attribution';   // v6
const send = (m) => navigator.sendBeacon('/rum', JSON.stringify({ name: m.name, value: m.value, rating: m.rating, attribution: m.attribution }));
onLCP(send); onINP(send); onCLS(send);
```
Track the p75 per route. INP attribution (input delay vs processing vs presentation, and
the longest script) points at the fix.
