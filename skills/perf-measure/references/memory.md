# Memory profiling and leak hunting

First decide which question you're answering:
- **Peak:** what allocated the high-water mark?
- **Churn:** what allocation volume is costing time in GC?
- **Leak:** what grows without bound across repetitions of an operation?

Each question uses a different tool and a different workload.

## Python

| Question | Tool |
|---|---|
| peak, including C extensions | `memray run --native -o m.bin app.py` (Linux best) → `memray stats --json -o m.json m.bin`, `memray flamegraph m.bin` |
| leak at exit | `PYTHONMALLOC=malloc memray run -o m.bin app.py && memray flamegraph --leaks m.bin` |
| growth over time | `memray flamegraph --temporal m.bin`; RSS sampling with `psutil` |
| churn / temporary allocations | `memray summary m.bin --temporary-allocations` |
| zero-dependency diff | `tracemalloc` snapshots (below) |
| who holds the objects | `objgraph.show_growth()`, `objgraph.show_backrefs(...)`, `gc.get_referrers` |
| test-time budget | pytest-memray `@pytest.mark.limit_memory("24 MB")`, `limit_leaks` |
| per-line memory with CPU | Scalene |

```python
import tracemalloc, gc
tracemalloc.start(25)
warm_up(); gc.collect(); s1 = tracemalloc.take_snapshot()
for _ in range(200): suspect_operation()
gc.collect(); s2 = tracemalloc.take_snapshot()
for st in s2.compare_to(s1, "traceback")[:10]:
    print(st); print("\n".join(st.traceback.format()[-6:]))
```
Gotchas:
- pymalloc hides small allocations. Use `PYTHONMALLOC=malloc` for leak hunts.
- memray can't follow `exec`. On macOS, `multiprocessing` defaults to `spawn`, so its
  children are invisible.
- Native reports must be generated on the machine that captured them.
- **CPython 3.14.0–3.14.4 shipped a GC change that caused memory pressure; it was reverted
  in 3.14.5. Upgrade before you hunt** unexplained growth on those versions.

Usual Python leaks:
- `lru_cache` / `cache` on methods (they keep `self` alive);
- module-level dicts and registries;
- closures that capture big objects;
- stored exception tracebacks;
- leftover `contextvars` / thread-locals;
- unbounded queues.

## Node / JS

```bash
node --trace-gc app.js                                  # one line per GC: frequent Mark-Compact = pressure
node --heap-prof --heap-prof-dir=.perf/<c>/heap app.js       # sampling allocation profile (.heapprofile)
node --heapsnapshot-signal=SIGUSR2 app.js & kill -USR2 $!   # on-demand snapshot
node --max-old-space-size=200 --heapsnapshot-near-heap-limit=2 app.js
```
- `process.memoryUsage()`: if `rss` grows while `heapUsed` stays flat, the growth is native,
  Buffer or ArrayBuffer memory (`external`, `arrayBuffers`), not JS objects.
- **Three-snapshot method:**
  1. Warm up, then take snapshot A.
  2. Repeat the operation N times, force `gc()` (`--expose-gc`), and take snapshot B.
  3. Repeat N more times and take snapshot C.

  Objects allocated between A and B that are still alive in C, with counts that scale with
  N, are the leak. Automate it with memlab:
  ```bash
  npx memlab find-leaks --snapshot-dir .perf/<c>/snaps
  npx memlab analyze unbound-collection --snapshot-dir .perf/<c>/snaps   # Maps/Sets/arrays that only grow
  ```
- Snapshots block the process and need about 2× heap memory. Avoid them on production
  containers near their limit.
- Usual JS leaks:
  - module-level caches without eviction;
  - listeners never removed (a `MaxListenersExceededWarning` is a hint);
  - timers and intervals;
  - closures capturing large scopes;
  - unbounded promise queues;
  - in the browser, detached DOM nodes held by JS.
- Bun: `bun --heap-prof-md`. Browser: memlab scenarios (`memlab run --scenario s.js`) or
  the Chrome DevTools MCP heap tools.

## Memory as a performance cost

Agents almost never optimize memory. On the SWE-Pro benchmark, experts reduced peak memory
171× while LLMs made essentially no memory improvements. Yet memory often *is* the time
cost: GC pauses, swapping, cache misses, container OOM restarts. Check peak RSS
(`perfkit abtest --all-metrics`) on every optimization. Treat a large `(garbage collector)`
share, or high GC time in `--trace-gc`, as a CPU finding:
- reduce allocations in the hot loop;
- reuse buffers;
- stream instead of materializing;
- use `__slots__` or TypedArrays for many small records.
