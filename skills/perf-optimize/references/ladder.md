# The optimization ladder

Work down from the top. Rungs higher up usually give orders of magnitude, while rungs lower
down give percentages. The research is consistent that agents choose small "convenience"
edits, such as identity checks, early exits, ad-hoc memoization and monkey patches, over
structural ones. The expert's win is usually a rung or two above the agent's.

Each rung lists what it typically buys, how to tell it applies from the profile, and the
semantics it puts at risk (see `guards.md`).

## 1. Do less work (×10–×1000)

- **Skip work whose result is unused.** Compute lazily, and only for the fields the caller
  reads. Push filters before joins and maps.
- **Avoid repeated work.** Parsing the same file per item, recompiling a regex per call,
  re-reading config per request, re-sorting after each insert, recomputing an aggregate
  from scratch.
- **Profile signal:** a high call count on an expensive frame (pstats `calls`, xtrace
  `calls`), or a frame whose inputs are identical across calls.
- **Risk:** you remove a side effect, or work that production *does* need. The benchmark
  checking less than production does is a gaming risk.

## 2. Better algorithm or data structure (×10–×1000 at scale)

- **Membership tests.** `x in list` / `arr.includes` in a loop → `set` / `Set` / `dict` /
  `Map`. Nested-loop joins → build a hash index once.
- **Queues.** `list.pop(0)` / `insert(0)` / `shift()` → `deque` or a ring buffer.
- **Selection.** Top-k by full sort → `heapq.nlargest` / partial selection. Sorted inserts →
  `bisect.insort`.
- **Immutable accumulation.** `acc = {...acc, k: v}`, `arr = [...arr, x]`, `s += piece` on
  huge strings → mutate a local accumulator, then `join` / `Object.fromEntries`.
- **Profile signal:** time grows superlinearly. Confirm with
  `perfkit scaling --cmd '... {n}' --sizes ...`; an exponent ≥1.5 at the tail means a hidden
  nested loop.
- **Risk:** iteration order (set vs list), duplicates, stability of sort.

## 3. Batch and restructure I/O (×2–×100)

- **N+1 queries** → `select_related` / `prefetch_related` / `selectinload`, or one `IN` query.
  **Per-row commits** → one transaction or a bulk insert.
- **One request per item** → batch endpoints, or keep-alive sessions.
- **Many small reads or writes** → buffered or whole-file I/O. Python-level CSV/JSON
  parsing of large data → pyarrow / polars / orjson / msgspec.
- **Shell: one process per line** → a single awk/jq/sed pass over the file. `find -exec \;`
  → `-exec +`.
- **Profile signal:** wall time ≫ CPU time; a wall-mode profile shows time in socket, DB or
  read frames; xtrace shows thousands of identical external commands.
- **Risk:** partial-failure semantics, transaction isolation, memory for whole-file reads.

## 4. Concurrency and parallelism (×cores for CPU-bound, ×in-flight for I/O-bound)

- **I/O:**
  - JS: sequential `await` in a loop → `Promise.all` with a concurrency bound (`p-limit`).
  - Python: `asyncio.gather` or a `ThreadPoolExecutor`.
  - Bash: `xargs -P`.
- **CPU:**
  - Python: `ProcessPoolExecutor` (pickling cost; `spawn` on macOS re-imports per worker),
    free-threaded 3.14t, or numpy/polars, which release the GIL.
  - Node: `worker_threads` / Piscina.
  - Browser: a Web Worker, or `scheduler.yield()` to break long tasks for INP.
- **Profile signal:** ELU ≈ 1 or one core pegged while others idle; independent awaits
  executed serially.
- **Risk:** this is a correctness change (ordering, races, rate limits, backpressure, shared
  state). Use proof-skills / formal-verify at R3+, or write a targeted race test, and bound
  the concurrency.

## 5. Caching and precomputation (×2–×1000 on hits; zero on misses)

- `functools.cache` / `lru_cache(maxsize=…)` on pure functions, `cached_property`,
  memoized selectors, HTTP caching, compile caches (`NODE_COMPILE_CACHE`), build caches.
- **Only cache what production repeats.** Size it, give it an eviction policy, and decide
  invalidation. A cache keyed on the benchmark's inputs is the textbook reward hack; the
  hold-out workload catches it.
- **Risk:** stale data, unbounded memory (a method `lru_cache` keeps `self` alive), thread
  safety.

## 6. Runtime-level and native (×1.1–×50)

- **Python:**
  - vectorize: numpy, polars lazy, pandas without `iterrows` / `apply(axis=1)`;
  - compile the kernel: mypyc for typed modules (2–5×), Cython, Rust via PyO3/maturin,
    numba `@njit` for numeric loops;
  - upgrade CPython (3.11 was about 25% faster than 3.10; the 3.15 JIT adds a few percent
    and is experimental).
- **JS:**
  - keep shapes monomorphic: initialize every field in the same order and don't `delete`;
  - use packed arrays and TypedArrays for numerics;
  - WASM for tight kernels: batch across the boundary, or marshalling eats the gain;
  - napi-rs for heavy native work.
- **Startup:**
  - Python: lazy imports (PEP 562 `__getattr__`, PEP 810 `lazy import` on 3.15), and no
    import-time work.
  - Node: drop barrel files, use lazy `import()`, bundle CLIs, enable `module.enableCompileCache()`.
- **Bash:** builtins and parameter expansion instead of `$(...)` externals; bash 5.3
  `${ cmd; }` for non-forking command substitution.

## 7. Micro-tuning (×1.01–×1.5, only inside a frame that is still hot)

- **Python:** hoist attribute and global lookups (`append = out.append`), comprehensions
  over loops with `.append`, `''.join`, `str` methods over regex, builtins (`sum`, `any`,
  `map`), `__slots__` / `dataclass(slots=True)` for millions of instances, type-stable code
  for the 3.11+ specializing interpreter.
- **JS:** fuse `map/filter/reduce` chains in hot loops, avoid closures allocated per
  iteration, `Map` for dynamic keys. Don't apply obsolete V8 folklore: try/catch,
  `arguments`, and forEach vs for no longer matter.
- **Measure each change separately.** Many micro-wins are below the MDE and must be
  reverted. This rung is where the research shows agents waste their effort.

## Language quick map

| Symptom in profile | Python first move | JS/TS first move | Bash first move |
|---|---|---|---|
| one hot frame, high self time | data structure / algorithm | data structure / algorithm | `awk` one-pass |
| many calls to a cheap frame | hoist / cache / batch | hoist / batch | remove per-line forks |
| wall ≫ CPU | batch I/O, async/threads | `Promise.all` with bound | `xargs -P`, fewer sequential network calls |
| high GC / allocation | generators, slots, avoid copies | avoid spread in loops, reuse buffers | n/a |
| startup dominates | `-X importtime`, lazy imports | compile cache, lazy `import()`, bundle | avoid sourcing big files, cache `$(tool init)` |
| page: long tasks, high TBT/INP | n/a | split work, worker, `scheduler.yield()`, virtualize lists | n/a |
