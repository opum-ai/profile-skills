# Python performance anti-patterns

Ordered by typical payoff. Each entry gives the **cue** (what to grep or read for), the
**fix**, and the **risk** (the semantics the fix can change).

## Algorithmic (×10–×1000 at scale)
| Cue | Fix | Risk |
|---|---|---|
| `if x in some_list` / `.index()` / `.count()` inside a loop | build a `set` / `dict` once outside the loop | order, unhashable items |
| nested loops joining two collections on a key | `dict` index on one side (hash join) | duplicate keys, order |
| `list.pop(0)`, `list.insert(0, x)` in loops | `collections.deque` | none |
| `sorted(...)` / `.sort()` inside a loop, or after each insert | sort once; `bisect.insort`; `heapq` for top-k | stability |
| `sum(...)`/`max(...)` over the same data recomputed per item | compute once / incrementally | none |
| string `+=` building a large string in a loop | `''.join(parts)` / `io.StringIO` | none |
| `copy.deepcopy` in loops | restructure to avoid copies; shallow copy of what changes | aliasing |
| recursion without memo on overlapping subproblems | `functools.cache` / DP table | memory |
| regex with nested quantifiers on untrusted input (`(a+)+`) | rewrite; anchor; limit length | matches |

## Repeated work
| Cue | Fix | Risk |
|---|---|---|
| file opened/read/parsed per item; config loaded per call | read once, pass in | staleness |
| `re.compile`/`re.match(pattern, ...)` with many distinct patterns per call | compile at module level (the `re` cache is 512 entries) | none |
| `json.loads(json.dumps(x))` for copying | real copy, or avoid | types (tuple→list) |
| same expensive pure function called with the same args in a loop | hoist out of the loop; `functools.cache` if pure | memory, staleness |
| per-element calls into numpy/pandas (`for i in range(len(arr)): arr[i]...`, `iterrows`, `apply(axis=1)`) | vectorized ops; polars | float semantics, NaN handling |
| `df.append` / `pd.concat` in a loop | collect a list, concat once | none |
| `dtype=object` arrays; numpy↔list conversions in loops | proper dtypes; stay in numpy | precision |

## I/O and concurrency
| Cue | Fix | Risk |
|---|---|---|
| `requests.get` in a loop without a `Session` | `requests.Session()` / `httpx.Client` (keep-alive); batch endpoint | none |
| sync I/O (`requests`, `open`, `time.sleep`, DB driver) inside `async def` | async clients, `await asyncio.to_thread(...)` | ordering |
| `await` in a loop over independent items | `asyncio.gather` / `TaskGroup` with a `Semaphore` bound | rate limits, error semantics |
| CPU-heavy work in threads (GIL) | `ProcessPoolExecutor`, numpy/polars (release the GIL), free-threaded 3.14t | pickling cost; `spawn` import cost on macOS |
| `subprocess.run` per item | one process for the batch, or in-process library | quoting, errors |
| logging with eager formatting in hot loops (`log.debug(f"...")`) | `log.debug("%s", x)`, `isEnabledFor` | none |

## Memory
| Cue | Fix | Risk |
|---|---|---|
| reading a whole large file / result set into a list to iterate once | iterate lazily; `yield`; DB cursor `iterator()` | re-iteration |
| millions of small objects with `__dict__` | `__slots__` / `dataclass(slots=True)` / NamedTuple / arrays | dynamic attrs |
| `functools.lru_cache` on methods / unbounded module dicts | bound it; key on ids that don't retain `self`; `weakref` | leaks |
| building intermediate lists for `any`/`all`/`sum` | generator expressions | none |

## Startup
| Cue | Fix |
|---|---|
| heavy imports (pandas, numpy, torch, boto3, big pydantic models) at module top of a CLI | import inside the command functions; PEP 562 lazy attribute; 3.15 `lazy import` |
| work at import time (compiling big regexes, reading files, network) | do it on first use |

## Usually not worth flagging
- micro-differences between `for` + `.append` and a comprehension, `dict()` vs `{}`, or
  f-strings vs `%`, **outside a proven hot loop**;
- try/except on the non-raising path (zero-cost since 3.11);
- `len(x) == 0` vs `not x`.

Static helper: `ruff check --select PERF,C4,SIM,FURB`. PERF401 (use a comprehension) and
PERF203 (try in a loop) are hints, only relevant where hot.
