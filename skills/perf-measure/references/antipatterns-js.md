# JavaScript / TypeScript (Node, Bun, Deno) performance anti-patterns

## Algorithmic and allocation
| Cue | Fix | Risk |
|---|---|---|
| `arr.includes/indexOf/find/filter` inside a loop or `.map` | build a `Set`/`Map` index once | order, `NaN`/object identity semantics |
| `acc = {...acc, [k]: v}` / `arr = [...arr, x]` in reducers or loops | mutate a local accumulator; `push`; `Object.fromEntries` once | immutability expectations of callers |
| `.map().filter().reduce()` chains over large arrays in hot paths | one loop | readability |
| `JSON.parse(JSON.stringify(x))` to clone | `structuredClone` (handles Map/Date/cycles) or targeted copy; avoid cloning | Date/undefined/Map behavior differs |
| `JSON.stringify` used for equality/keys in loops | stable key function | key collisions |
| sort comparator doing heavy work (parsing dates, `localeCompare` with new `Intl` each call) | precompute keys (Schwartzian transform); reuse `Intl.Collator` | stability |
| string `+=` for huge outputs then indexing/splitting | array + `join`, or stream | none |
| regex with nested quantifiers on user input | linear rewrite, anchoring, length limit | matches |
| object used as a dynamic map with frequent add/delete; `delete obj.k` in hot code | `Map`; set to `undefined` | `Object.keys` semantics |
| objects of one "type" created with different key orders / fields added later | initialize all fields in one place, same order (monomorphic) | none |
| holey arrays (`new Array(n)` filled out of order), mixed element kinds | `Array.from({length:n}, f)`, push in order, TypedArrays for numbers | none |

## Async and I/O
| Cue | Fix | Risk |
|---|---|---|
| `for (...) { await fetch/db(...) }` over independent items | `Promise.all` with a concurrency bound (`p-limit`) | rate limits, partial failure semantics |
| `readFileSync`/`execSync`/`pbkdf2Sync`/`zlib.*Sync` on request paths | async APIs; cache; worker | ordering |
| CPU-heavy work on the main thread of a server | `worker_threads` / Piscina; chunk + `setImmediate` | complexity |
| a new HTTP client/agent per request; no keep-alive | shared `undici.Agent` / fetch dispatcher | none |
| unbounded `Promise.all` over thousands of items | bounded concurrency | memory, overload |
| `console.log` / sync logging in hot paths | async logger (pino), level guards | none |
| listeners added per request/component and never removed | remove / AbortSignal; `once` | leaks |
| module-level caches without eviction | LRU (`lru-cache`), `WeakMap` | leaks, staleness |

## Startup and build
| Cue | Fix |
|---|---|
| barrel files (`index.ts` re-exporting everything) imported by entry points | direct imports; `sideEffects: false`; lazy `import()` |
| big dependency imported at top of a CLI for a rare subcommand | `await import()` inside the subcommand |
| reading/parsing big JSON/config at import time | lazy on first use; `NODE_COMPILE_CACHE` for code |
| TS: giant unions, deep conditional/recursive types, type-level libraries on hot generic paths | annotate return types; split types; `isolatedDeclarations`; measure with `--extendedDiagnostics` |
| babel/ts-loader in bundling | esbuild/swc/oxc transforms; type-check separately |

## Usually not worth flagging
- try/catch, `arguments`, forEach vs for, `let` vs `const`, `==` vs `===` for speed;
- `async` functions that could be sync, outside hot paths;
- micro-differences in loop style outside proven hot loops.
