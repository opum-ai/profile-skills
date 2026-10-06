# Browser / frontend performance anti-patterns

| Cue | Effect | Fix | Risk |
|---|---|---|---|
| reading `offsetWidth/Height`, `getBoundingClientRect`, `scrollTop`, `getComputedStyle` after writing styles, in a loop | forced synchronous layout per iteration (layout thrashing) → long tasks, bad INP | batch reads then writes; `requestAnimationFrame`; CSS instead of JS measurement; ResizeObserver | visual equivalence |
| rendering thousands of rows/DOM nodes | slow layout/paint, memory | virtualization (TanStack Virtual), pagination, `content-visibility: auto` | find-in-page, a11y |
| heavy synchronous work in event handlers (sort/filter big arrays, JSON parse) | INP | memoize, precompute, `useTransition`/`useDeferredValue`, Web Worker, `scheduler.yield()` | ordering of updates |
| React: new object/array/function props every render to memoized children; context value object recreated each render | cascading re-renders | stable references, split contexts, move state down, React Compiler | stale closures |
| React: component defined inside another component's render | remount every render | hoist component | none |
| React: missing/unstable `key` (index keys on reorderable lists) | DOM churn, state bugs | stable ids | — |
| `useEffect` that sets state on every render / fetch waterfalls in nested components | extra renders, slow loads | derive state; fetch in parallel at route level | — |
| hero/LCP image `loading="lazy"`, no `fetchpriority="high"`, no dimensions | late LCP, CLS | eager + `fetchpriority="high"` + `width/height`; responsive `srcset` | — |
| render-blocking `<script>` in `<head>` without `defer`/`type=module`; large CSS | late FCP/LCP | defer, split, inline critical CSS | execution order |
| images/ads/embeds/fonts without reserved space | CLS | `aspect-ratio`, size attributes, `font-display` + metric overrides | — |
| whole-library imports (lodash, moment, icon sets) / large deps for one function | bundle size, parse/compile time | per-function imports, smaller libs, native APIs | behavior differences |
| polling with `setInterval` + full re-render | CPU, battery | event-driven updates, diffing | — |
| animations on `top/left/width/height` or `box-shadow`/`filter` | layout/paint per frame | animate `transform`/`opacity` | — |
| listeners/observers/timers not cleaned up in effects | leaks across navigations | cleanup returns, AbortController | — |

Measure with `scripts/browser_trace.mjs`: `Layout` event counts, long tasks, TBT,
the max interaction duration (`--interact`), and LCP/CLS medians. Compare base and head
production builds under the same CPU throttle.
