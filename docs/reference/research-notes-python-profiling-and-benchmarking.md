---
# yaml-language-server: $schema=../../.lore/schemas/reference.schema.json
type: Reference
title: "Research notes: Python profiling and benchmarking"
tags:
  - research
summary: Python profilers (py-spy, pyinstrument, Scalene, Tachyon, cProfile), memory tools, benchmark harnesses, async/DB profiling and agent-optimization findings, as of Oct 2026.
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:00:48.310Z
---

# Research notes: Python profiling and benchmarking

Raw research notes gathered 2026-10-05 by three parallel research passes (web sources cited inline; items not confirmed against a primary source are marked unverified). The distilled design input is [the state-of-the-art summary](state-of-the-art-in-performance-profiling-and-agent-driven-optimization.md).


Scope: what Claude Code (or any coding agent) should run on **macOS (Apple Silicon) dev boxes** and **Linux CI**
to find, fix, and prove Python performance changes. Commands are copy-pasteable; anything I could not
confirm from a primary source is marked **(unverified)**.

Versions were checked against PyPI's JSON API on 2026-10-05 (`https://pypi.org/pypi/<pkg>/json`):

| Tool | Latest | Released | Notes |
|---|---|---|---|
| CPython 3.15 | 3.15.0rc3 | 2026-10-02 | Final expected **2026-10-09** ([PEP 790](https://peps.python.org/pep-0790/)) |
| py-spy | 0.4.2 | 2026-04-24 | Adds Python 3.14 support ([releases](https://github.com/benfred/py-spy/releases)) |
| scalene | 2.3.0 | 2026-05-12 | New `scalene run` / `scalene view` CLI |
| pyinstrument | 5.1.3 | 2026-07-29 | |
| memray | 1.20.0 | 2026-08-07 | Adds 3.15 support, `transform speedscope` |
| pytest-memray | 1.11.0 | 2026-09-17 | |
| austin-dist | 4.0.0 | 2025-11-01 | Austin 4, pip-installable |
| yappi | 1.7.6 | 2026-03-17 | |
| line-profiler | 5.0.2 | 2026-02-23 | `kernprof` reads `pyproject.toml` config |
| viztracer | 1.1.1 | 2025-11-11 | |
| pyperf | 2.10.0 | 2026-02-07 | |
| pytest-benchmark | 5.3.0 | 2026-08-23 | New `--benchmark-precision/--benchmark-confidence` |
| pytest-codspeed | 5.0.3 | 2026-05-22 | Py 3.9–3.15 incl. free-threaded |
| CodSpeedHQ/action | v5.4.0 | 2026-10-02 | GitHub Action |
| asv | 0.6.6 | 2026-06-27 | |
| tuna | 0.5.15 | 2026-05-19 | |
| pyroscope-io | 1.2.5 | 2026-10-02 | |
| django-silk 5.6.0, django-debug-toolbar 8.0.0, SQLAlchemy 2.1.3, Cython 3.3.0, mypy(c) 2.4.0, maturin 1.15.0, PyO3 0.29.3, numba 0.68.0, numpy 2.5.3, polars 1.44.2, ruff 0.16.10 | | | |
| nplusone | 1.0.0 | **2018-05-21** | Unmaintained; prefer alternatives below |

---

## 0. The agent's loop (the one thing to internalize)

Research on LLM performance agents (Section 7) converges on one lesson: **measure → localize with a
profiler → change one thing → re-verify correctness → re-measure with statistics → keep going past the
first win**. Agents that skip profiling optimize the wrong function. Agents that skip correctness tests
introduce regressions. Agents that benchmark their own repeated inputs "win" by caching, which is
reward hacking.

```bash
# 1. Baseline: correctness, then a rigorous timing of the real workload
pytest -q
python -m pyperf command -o base.json -- python workload.py            # or pyperf timeit / pytest-benchmark
# 2. Localize (sampling profiler, machine-readable output)
py-spy record -f speedscope -o prof.speedscope.json -- python workload.py   # <=3.14
python -m profiling.sampling run --collapsed -o stacks.txt workload.py     # 3.15+
# 3. Edit ONE hotspot; 4. re-run tests; 5. compare with significance
python -m pyperf command -o new.json -- python workload.py
python -m pyperf compare_to base.json new.json --table
```

---

## 1. CPU profilers

### 1.1 Decision table

| Need | Default pick | Why |
|---|---|---|
| "Where is time going?" in a script/test, Py ≤3.14 | **py-spy** `record` (Linux) / **pyinstrument** (macOS without sudo) | Low overhead, no code changes |
| Same, on Python 3.15+ | **`python -m profiling.sampling`** (Tachyon, stdlib) | Built in, up to 1 MHz sampling, many output formats |
| Exact call counts / call graph | `cProfile` = `profiling.tracing` (3.15) | Deterministic; inflates cost of small functions |
| Line-level CPU + memory + Python-vs-native split + copy volume | **Scalene** | Per-line, JSON output by default |
| Hot function, which *line* | **line_profiler** (`kernprof -l`) | Deterministic per line |
| Attach to a live/hung process | py-spy `dump`/`top`/`record --pid`; 3.15: `profiling.sampling attach/dump` | Out-of-process |
| Multithreaded / asyncio / gevent with exact per-thread stats | **yappi** | Per-thread and coroutine-aware wall time |
| Async request latency | pyinstrument (async-aware) or Tachyon `--async-aware` | Shows the `await` chain |
| Timeline (ordering, concurrency, gaps) | **VizTracer** → Perfetto | Full tracing, Chrome trace JSON |
| Native + Python in `perf` / eBPF, Linux | `python -X perf` / `-X perf_jit` + `perf` | System-wide, kernel visibility |
| Production continuous profiling | Pyroscope (`pyroscope-io`) or OTel eBPF profiler | Always-on, low overhead |

### 1.2 Machine-readable outputs an agent can parse

| Tool | Parseable formats |
|---|---|
| cProfile / profiling.tracing | `.prof` pstats (marshal). Load with `pstats.Stats`. No native JSON |
| profiling.sampling (3.15) | `--pstats` file, `--collapsed` (folded stacks text), `--gecko` (Firefox Profiler JSON), `--binary` (replayable), HTML `--flamegraph`/`--heatmap` |
| py-spy | `-f speedscope` (JSON), `-f raw` (collapsed stacks text), `-f chrometrace` (JSON), `-f flamegraph` (SVG) |
| pyinstrument | `-r json`, `-r speedscope`, `-r pstats`, `-r session` (`.pyisession`, reloadable), `-r text`, `-r html` |
| Scalene | JSON by default (`scalene-profile.json`) |
| Austin | MOJO binary → collapsed stacks via `austin-python` tools (**unverified** exact converter names in v4) |
| yappi | `save(path, type="pstat"|"callgrind")` |
| VizTracer | Chrome Trace Event JSON (`.json`, `.json.gz`) |
| line_profiler | `.lprof`, text via `python -m line_profiler -rmt file.lprof` |
| memray | `stats --json`, `transform csv|gprof2dot|speedscope` |

**Agent tip:** prefer **collapsed stacks** (`frame;frame;frame count` per line) for LLM consumption. They're
compact, greppable, and easy to aggregate with `sort | head`. Use pstats via a 3-line script for
top-N tables:

```bash
python - <<'EOF'
import pstats; s = pstats.Stats("out.prof"); s.strip_dirs().sort_stats("cumulative").print_stats(25)
s.sort_stats("tottime").print_stats(15)
EOF
```

### 1.3 cProfile / `profiling.tracing` / `profile`

```bash
python -m cProfile -o out.prof -s cumtime app.py        # -s only applies when no -o
python -m cProfile -o out.prof -m mypkg.cli args
python -m profiling.tracing -o out.prof -m mypkg.cli    # 3.15 name; cProfile alias stays forever
snakeviz out.prof                                       # browser icicle (human use)
gprof2dot -f pstats out.prof | dot -Tsvg -o callgraph.svg
```

- Python 3.15 (PEP 799, **Final**) adds the `profiling` package: `profiling.tracing` (cProfile's new home) and
  `profiling.sampling` (Tachyon). The pure-Python **`profile` module is deprecated in 3.15 and slated for
  removal in 3.17** ([profiling docs](https://docs.python.org/3.15/library/profiling.html),
  [tracing docs](https://docs.python.org/3.15/library/profiling.tracing.html)).
- Gotchas: deterministic overhead distorts code with many tiny calls (it can make a function-call-heavy
  path look 2× worse than reality). It is main-thread only unless you enable it per thread, and it isn't
  async-aware (the event loop dominates). Use it for **call counts** ("why is `normalize()` called 1.2M
  times?"), not for precise percentages.
- `pytest --benchmark-cprofile=cumtime` (pytest-benchmark) and `asv profile` reuse cProfile.

### 1.4 Tachyon: `python -m profiling.sampling` (Python 3.15)

Status: PEP 799 **Final**. Ships in 3.15. 3.15.0rc3 shipped 2026-10-02, and final is due 2026-10-09
([What's New 3.15](https://docs.python.org/3.15/whatsnew/3.15.html)). It's built on the PEP 768 remote-debugging
interface from 3.14. Docs: <https://docs.python.org/3.15/library/profiling.sampling.html>.

```bash
python -m profiling.sampling run script.py                       # pstats table to stdout (default 1 kHz)
python -m profiling.sampling run -m mypkg.cli arg1               # module
python -m profiling.sampling run -r 20khz -a --flamegraph -o fg.html script.py   # all threads
python -m profiling.sampling run --collapsed -o stacks.txt script.py
python -m profiling.sampling run --gecko -o prof.json script.py  # Firefox Profiler JSON
python -m profiling.sampling run --heatmap --opcodes script.py   # per-line + bytecode (specialization)
python -m profiling.sampling run --mode=cpu|gil|wall|exception ...
python -m profiling.sampling run --async-aware --async-mode=all --flamegraph app.py
python -m profiling.sampling run --subprocesses script.py         # one output per child PID (max 100)
python -m profiling.sampling attach -d 30 --flamegraph -o prod.html <PID>
python -m profiling.sampling attach --live <PID>                  # top-like TUI (curses)
python -m profiling.sampling dump -a --async-aware <PID>          # one-shot stacks of a hung process
# record & replay + differential flame graph (great for before/after in a PR)
python -m profiling.sampling run --binary -o base.bin script.py
python -m profiling.sampling run --diff-flamegraph base.bin -o diff.html script.py
python -m profiling.sampling replay --collapsed -o stacks.txt base.bin
```

Other flags: `--native` (include `<native>` frames), `--no-gc`, `--blocking` (pause target per sample;
use ≥1000 µs intervals), `--sort nsamples|tottime|cumtime|...`, `-l/--limit`, `--realtime-stats`, `--browser`.

Gotchas (from the docs):
- **Profiler and target must be the same minor version** (3.15↔3.15). Pre-releases must match exactly.
  Free-threaded and GIL builds cannot attach to each other. **For 3.12–3.14 targets, keep using py-spy.**
- Permissions: Linux needs root, `CAP_SYS_PTRACE`, or `ptrace_scope=0`. **macOS needs root (sudo)**, the
  `com.apple.security.cs.debugger` entitlement, or SIP disabled (don't). The docs only describe this for
  attaching. Whether `run` on macOS also needs sudo is **unverified**, so assume yes.
- `--async-aware` can't be combined with `--native`, `--no-gc`, `--all-threads`, or `--mode=cpu|gil`. asyncio
  must already be imported. `--gecko` ignores `--mode`.
- It's statistical. For runs under ~1 s, exact call counts, or 1–2 % differences, use tracing or a benchmark.
- 3.15 also enables frame pointers by default (**PEP 831**, Final), so `perf`/eBPF native unwinding of
  CPython is cheap and reliable.

### 1.5 py-spy (0.4.2, Python 2.3–3.14)

```bash
py-spy record -o prof.svg -- python app.py                      # flame graph SVG
py-spy record -f speedscope -o prof.json -- python app.py       # JSON for agents / speedscope.app
py-spy record -f raw -o stacks.txt --rate 250 -- python app.py  # collapsed stacks
py-spy record --pid 1234 --duration 30 -f speedscope -o p.json
py-spy record --subprocesses --idle --gil --threads -- python app.py
py-spy record --native -- python app.py                         # Linux/Windows only
py-spy top --pid 1234
py-spy dump --pid 1234 --locals                                 # hung process diagnosis
py-spy record --nonblocking --pid 1234 ...                      # don't pause target (less accurate)
```

- **macOS: always requires `sudo`** ([README](https://github.com/benfred/py-spy)). It **cannot profile the SIP-protected
  `/usr/bin/python3`**. Use a uv, Homebrew, or pyenv interpreter. Apple Silicon wheels exist.
  **`--native` is not supported on macOS** and errors out
  ([issue #188](https://github.com/benfred/py-spy/issues/188)).
  For an agent on a Mac without passwordless sudo, py-spy is often unusable. Fall back to
  pyinstrument, Scalene, or cProfile, which run in-process with no privileges.
- Linux: launching a child (`record -- python ...`) needs no root. Attaching to an existing PID needs root or
  `CAP_SYS_PTRACE` (Docker: `--cap-add SYS_PTRACE`; k8s: `securityContext.capabilities.add: [SYS_PTRACE]`).
- `--gil` needs debug symbols. Idle detection is heuristic. PyPy isn't supported.
- Python 3.15 support: not in 0.4.2 (**unverified** whether a newer build adds it). Use Tachyon for 3.15.

### 1.6 Scalene (2.3.0): CPU + GPU + memory, per line

```bash
scalene run prog.py                         # writes scalene-profile.json (machine-readable!)
scalene run --cpu-only prog.py              # faster, CPU only
scalene run --memory --gpu prog.py          # memory/GPU explicitly (memory may be opt-in in 2.x; see --help)
scalene run -o out.json --profile-only mypkg,src/ prog.py --- --prog-arg 1
scalene run --use-virtual-time prog.py      # CPU time only (exclude I/O/blocking)
scalene run --memory-leak-detector prog.py  # experimental
scalene view --cli                          # terminal text
scalene view --html | --standalone          # HTML
scalene run --off prog.py; python3 -m scalene.profile --on --pid <PID>   # background toggle
```

Jupyter: `%load_ext scalene`, `%scrun`, `%%scalene`. It reports Python vs native vs system time per line,
**copy volume** (MB/s copied across the Python/native boundary, e.g. accidental numpy→list conversion),
memory growth per line, and async `await` time with concurrency per line. It uses `sys.monitoring`. Overhead is
about 10–35 % ([README](https://github.com/plasma-umass/scalene)). **AI optimization proposals** are
available in the web UI (OpenAI, Azure, Bedrock, Ollama; `scalene view --api-keys-from-env` prefills keys
from `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and others). An agent doesn't need this, because it is the LLM. Feed it the JSON.
The older one-shot CLI (`scalene --cli --json --outfile`) has been reorganized under `run`/`view` in 2.x.
Don't rely on the old flags.

### 1.7 pyinstrument (5.1.3): statistical, async-aware, great HTML

```bash
pyinstrument script.py                         # text tree to terminal
pyinstrument -r json -o prof.json script.py    # machine-readable
pyinstrument -r speedscope -o prof.ss.json -m mypkg.cli
pyinstrument -r html -o prof.html -t script.py # -t/--timeline keeps ordering
pyinstrument -i 0.0001 --show-all script.py    # 100 µs interval; don't hide library frames
pyinstrument -m pytest tests/test_slow.py      # profile a test run
pyinstrument --load-prev <id> -r html          # re-render previous session
```

API: `with pyinstrument.profile(): ...`, `@pyinstrument.profile()`, and `Profiler(async_mode="enabled"|"strict"|"disabled")`.
In async mode, time spent awaiting shows as `<await>` under the awaiting coroutine.
Middleware recipes: Django (`pyinstrument.middleware.ProfilerMiddleware`, `?profile`,
`PYINSTRUMENT_PROFILE_DIR`), Flask, FastAPI (`@app.middleware("http")`), Falcon, Litestar, aiohttp
([guide](https://pyinstrument.readthedocs.io/en/latest/guide.html)). It runs in-process with no sudo, which makes it the **best
default on macOS for an agent**. It only samples the main thread by default, and it hides library frames unless you pass `--show-all`.

### 1.8 Austin 4 (`pip install austin-dist`)

A pure-C frame-stack sampler supporting Python 3.9–3.14. Flags: `-i` interval (default 100 µs), `-o`, `-m` memory, `-f` full
(time+memory), `-p PID`, `-C` children, `-x` exposure seconds, `-P` pipe, `-w` dump stacks. Output is MOJO binary,
convertible to collapsed stacks. Companions: austin-tui, austin-web, VS Code extension. **Needs sudo on
macOS.** Pick it over py-spy when you want memory+time sampling in one zero-instrumentation tool, or the
VS Code integration ([repo](https://github.com/P403n1x87/austin)).

### 1.9 yappi (1.7.6): multithread / asyncio / gevent

```python
import yappi
yappi.set_clock_type("wall")     # "cpu" for CPU-bound threads; "wall" for coroutines/IO
yappi.start()
run_workload()
yappi.stop()
stats = yappi.get_func_stats()
stats.save("out.prof", type="pstat")      # or "callgrind" -> KCachegrind/qcachegrind
yappi.get_thread_stats().print_all()
# per-thread: yappi.get_func_stats(filter={"ctx_id": tid})
```

Use it when you need **per-thread** attribution or correct coroutine wall time. cProfile mis-attributes both.
It's a tracing profiler, so it carries overhead like cProfile ([repo](https://github.com/sumerc/yappi)).

### 1.10 line_profiler / kernprof (5.0.2)

```bash
kernprof -l -v script.py                       # needs @profile on target funcs (-b injects builtin)
kernprof -l -v -r -u 1e-3 script.py            # rich output, ms units
kernprof -l -p mypkg.core,mypkg.io script.py   # --prof-mod: profile modules/functions w/o decorators
kernprof -l --prof-imports -p script.py script.py   # auto-profile everything the script imports
kernprof -l -m mypkg.cli args                   # module mode
python -m line_profiler -rmt script.py.lprof   # re-render saved results
LINE_PROFILE=1 python script.py                # with `from line_profiler import profile` (4.1+)
```

Options: `-z` skip zero-hit, `--summarize`, `-i N` periodic dump, `--config` / `[tool.line_profiler]` in
`pyproject.toml` ([kernprof CLI](https://kernprof.readthedocs.io/en/latest/auto/kernprof.html)). **Only profile 1–5
functions you already identified with a sampler.** Line tracing overhead is large.

### 1.11 VizTracer (1.1.1): full timeline

```bash
viztracer -o trace.json -- python app.py arg     # Chrome trace event JSON; view in Perfetto/vizviewer
viztracer --tracer_entries 5000000 --max_stack_depth 20 --ignore_c_function --min_duration 0.2ms app.py  # (min_duration unverified syntax)
viztracer --log_async --log_func_args -m mypkg
vizviewer trace.json
```

It's a circular buffer (default 1M entries; old events drop). Use it for ordering, concurrency, and latency gaps, not
for aggregate hot spots ([docs](https://viztracer.readthedocs.io/en/latest/basic_usage.html)).

### 1.12 `perf` trampoline (Linux only, 3.12+)

```bash
python -m sysconfig | grep HAVE_PERF_TRAMPOLINE                  # check support
perf record -F 9999 -g -o perf.data python -X perf app.py        # needs frame pointers (default in 3.15, PEP 831)
perf report -g -i perf.data
# no frame pointers -> DWARF JIT mode (3.13+), perf >= 6.8
perf record -F 9999 -g -k 1 --call-graph dwarf -o perf.data python -X perf_jit app.py
perf inject -i perf.data --jit -o perf.jit.data && perf report -g -i perf.jit.data
PYTHONPERFSUPPORT=1 ...   # env equivalent; or sys.activate_stack_trampoline("perf")
```

Shows Python *and* C/kernel frames together ([howto](https://docs.python.org/3/howto/perf_profiling.html)).
Not available on macOS. There, use Instruments, or `samply` (**unverified** for Python symbolization).

---

## 2. Memory

### 2.1 Picks

| Question | Tool |
|---|---|
| "What allocated the peak?" (incl. C extensions) | **memray** (`--native` on Linux) |
| Leak in a long-running process | memray `--leaks` flame graph, or tracemalloc snapshot diffs |
| Memory regression gate in tests | **pytest-memray** `limit_memory` / `limit_leaks` |
| Per-line memory + CPU together | Scalene |
| Which objects are piling up / who references them | objgraph, guppy3, `gc.get_referrers` |
| Zero-dependency, in CI | `tracemalloc` (stdlib) |

### 2.2 tracemalloc (stdlib)

```bash
python -X tracemalloc=25 app.py          # or PYTHONTRACEMALLOC=25
```
```python
import tracemalloc, gc
tracemalloc.start(25)
s1 = tracemalloc.take_snapshot()
run_suspect_operation_n_times()
gc.collect()
s2 = tracemalloc.take_snapshot()
for stat in s2.compare_to(s1, "traceback")[:10]:
    print(stat); print("\n".join(stat.traceback.format()))
print(tracemalloc.get_traced_memory())   # (current, peak)
```
It only sees allocations made through Python's allocators (misses most native/C allocations). Overhead is about 2–4×
with deep tracebacks. Filter with `snapshot.filter_traces([tracemalloc.Filter(False, "<frozen importlib._bootstrap>")])`.

### 2.3 memray (1.20.0; Linux + macOS, no Windows)

```bash
memray run -o out.bin app.py                 # or -m pkg / -c "code"; -f overwrite
memray run --native -o out.bin app.py        # C/C++ frames (best on Linux; macOS stacks are poor)
memray run --trace-python-allocators ...     # see pymalloc allocations (or PYTHONMALLOC=malloc)
memray run --follow-fork --aggregate ...     # children; small files (no stats/temporal)
memray run --live app.py                     # TUI
memray attach <PID> [-o out.bin --duration 30]; memray detach <PID>   # needs gdb or lldb + ptrace perms
memray flamegraph out.bin                    # peak-memory icicle HTML
memray flamegraph --leaks out.bin            # leaked at exit (run with PYTHONMALLOC=malloc)
memray flamegraph --temporal out.bin         # memory over time
memray summary out.bin --temporary-allocations   # finds list-growth / churn
memray table|tree|summary out.bin
memray stats --json -o stats.json out.bin    # agent-parseable
memray transform csv|gprof2dot|speedscope out.bin
```

Gotchas ([supported envs](https://bloomberg.github.io/memray/supported_environments.html),
[run](https://bloomberg.github.io/memray/run.html)):
- Native-mode reports must be generated **on the same machine** as the capture.
- pymalloc hides small allocations (≤512 B) reused from arenas. Use `PYTHONMALLOC=malloc` for leak hunting.
- You can't follow `exec`. **macOS multiprocessing defaults to `spawn` (exec)**, so children are invisible there.
- Cython functions only appear with `--native`.

### 2.4 pytest-memray (1.11.0)

```bash
pytest --memray [--memray-bin-path=.memray] [--most-allocations=10] [--native] tests/
```
```python
@pytest.mark.limit_memory("24 MB")                 # fail if peak > 24 MB
def test_parse(): ...
@pytest.mark.limit_leaks("1 MB", filter_fn=ignore_caches)   # per-call-stack leak budget
def test_loop(): ...
@pytest.mark.limit_leaked_objects(...)              # Python 3.13.3+
```
The docs say plainly that it's "very challenging" to write zero-leak tests (re cache, logging, interning). Budget
small amounts and use `filter_fn` ([usage](https://pytest-memray.readthedocs.io/en/latest/usage.html)).

### 2.5 Object-level leak hunting

```python
import objgraph, gc
objgraph.show_growth(limit=10)        # call before/after N iterations; shows types that grew
objgraph.show_backrefs(objgraph.by_type("MyNode")[:3], max_depth=5, filename="refs.png")
from guppy import hpy; h = hpy(); print(h.heap())    # guppy3 3.1.7
gc.set_debug(gc.DEBUG_SAVEALL); gc.collect(); len(gc.garbage)   # uncollectable cycles
```
**Leak workflow:**
1. Reproduce in a loop and watch RSS (`psutil.Process().memory_info().rss`).
2. Use tracemalloc snapshot diffs, or memray `--leaks` with `PYTHONMALLOC=malloc`.
3. Use objgraph backrefs to find the holder.

Usual culprits are unbounded `functools.lru_cache`/`cache` on methods (they keep `self` alive), module-level dicts and registries,
closures capturing large objects, exception tracebacks stored in variables, `__del__` cycles, and
thread-local or contextvar leftovers.
Note that **3.14.0–3.14.4 shipped an incremental GC that caused production memory pressure. It was reverted in
3.14.5+ and 3.15** ([What's New 3.15](https://docs.python.org/3.15/whatsnew/3.15.html)). If you see
unexplained memory growth on 3.14.0–3.14.4, upgrade before you hunt.

---

## 3. Benchmarking

### 3.1 Picks

| Situation | Tool |
|---|---|
| Micro/macro benchmark with real statistics, A/B two branches/interpreters | **pyperf** |
| Benchmarks living in the pytest suite, local regression gate | **pytest-benchmark** |
| Low-noise CI regression detection on shared runners | **CodSpeed** (`pytest-codspeed`, CPU simulation) |
| Historical tracking across many commits, bisecting regressions | **asv** |
| Self-hostable continuous benchmarking + thresholds over any harness | **Bencher** |
| One-liner sanity check | `python -m timeit` (with caveats) |

### 3.2 pyperf (2.10.0): the rigorous default

```bash
python -m pyperf timeit -s "import mod; d=mod.data()" "mod.f(d)" -o base.json
python -m pyperf timeit --rigorous ... | --fast ...         # presets (more/fewer processes and values)
python -m pyperf timeit -p 20 -n 3 -w 1 -l 1000 ...         # processes/values/warmups/loops
python -m pyperf command -o cli.json -- python -m mycli --help   # whole-process wall time
python -m pyperf compare_to base.json new.json --table -G --min-speed=2
python -m pyperf stats base.json; python -m pyperf hist base.json; python -m pyperf check base.json
sudo python -m pyperf system tune     # Linux: governor=performance, no turbo, IRQ affinity, etc.
python -m pyperf system show|reset
```
- It spawns **multiple worker processes** (default 20 for timeit) to average out ASLR, hash seeds, and layout effects.
  It calibrates loops and discards warmups.
- `compare_to` marks a result "significant" using a two-sample, two-tailed Student's t-test. `--min-speed`
  ignores differences below N %. `check` warns when stdev > 10 % of the mean
  ([CLI docs](https://pyperf.readthedocs.io/en/latest/cli.html)).
- `system tune` is **Linux-only** (isolcpus/nohz_full/rcu_nocbs advice, turbo, governor, perf sample rate)
  ([system docs](https://pyperf.readthedocs.io/en/latest/system.html)). On macOS/Apple Silicon you can't pin
  P-cores or disable boost the same way. Run on AC power, close other apps, and accept higher noise. Use
  CodSpeed or a quiet Linux box for decisions under 5 %.
- Script API for complex setups: `runner = pyperf.Runner(); runner.bench_func("name", fn, arg)`. Don't put
  `print` in the worker. Use `--inherit-environ` when env vars matter.

### 3.3 pytest-benchmark (5.3.0)

```python
def test_parse(benchmark):
    result = benchmark(parse, payload)            # auto-calibrated rounds/iterations
    assert result == expected                     # ALWAYS assert correctness in the benchmark
def test_build(benchmark):
    benchmark.pedantic(build, setup=make_input, rounds=50, iterations=1, warmup_rounds=2)
```
```bash
pytest --benchmark-only --benchmark-autosave                    # store in .benchmarks/
pytest --benchmark-only --benchmark-compare --benchmark-compare-fail=min:5%   # gate vs last saved
pytest --benchmark-only --benchmark-compare=0001 --benchmark-compare-fail=mean:0.001  # absolute seconds
pytest --benchmark-json=bench.json --benchmark-disable-gc --benchmark-warmup=on
pytest --benchmark-precision=0.02 --benchmark-confidence=0.99   # 5.3: stop when ±2 % at 99 %
pytest --benchmark-disable    # in normal test runs: execute once, no timing
pytest-benchmark compare 0001 0002 --csv=cmp.csv
```
([usage](https://pytest-benchmark.readthedocs.io/en/latest/usage.html)). Gotchas: `--benchmark-compare-fail`
compares against **one** prior run with no significance test. Gate on `min` (least noisy) and use a
generous threshold (≥5–10 %) on shared CI runners, or you'll get flaky failures. Don't run benchmarks under
`pytest-xdist` or coverage. Setup in `pedantic(setup=...)` runs outside timing.

### 3.4 CodSpeed (`pytest-codspeed` 5.0.3, `CodSpeedHQ/action` v5)

```bash
uv add --dev pytest-codspeed
pytest tests/bench --codspeed                                    # local: runs & validates, no reporting
pytest --codspeed --codspeed-mode=simulation|walltime|memory     # auto by default
pytest --codspeed --codspeed-warmup-time=0.5 --codspeed-max-time=2 --codspeed-max-rounds=100  # walltime
```
```yaml
# .github/workflows/codspeed.yml
jobs:
  benchmarks:
    runs-on: ubuntu-latest
    permissions: { contents: read, id-token: write }   # OIDC
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --dev
      - uses: CodSpeedHQ/action@v5
        with:
          mode: simulation
          run: uv run pytest tests/bench --codspeed
```
- It's compatible with the pytest-benchmark API (`benchmark` fixture, `@pytest.mark.benchmark`, `pedantic`).
- **CPU simulation** (formerly "instrumentation") runs each benchmark once under a modified Valgrind/Callgrind.
  It counts instructions plus L1/LL cache misses, which gives near-deterministic results on noisy shared runners.
  **It excludes syscalls/I-O** ([CPU instrument](https://codspeed.io/docs/instruments/cpu)). Use **walltime**
  for I/O-bound or multithreaded code. Walltime on shared GitHub runners is unreliable, so CodSpeed recommends its
  bare-metal **Macro Runners** (availability depends on plan). Pin toolchains, because compiler or dependency changes shift
  results ([variance doc](https://codspeed.io/docs/instruments/cpu/regression-causes)).
- Simulation is Linux-only in practice (Valgrind). On macOS, `--codspeed` just runs the benchmarks.

### 3.5 asv (0.6.6)

```bash
asv quickstart; asv machine --yes
asv run main^!                                 # single commit
asv run v1.0..main --steps 20                  # sample history
asv continuous --factor 1.1 --split main HEAD  # PR gate: fail if >10 % slower
asv compare main HEAD --sort ratio
asv find v1.0..main time_parse                 # bisect a regression
asv publish && asv preview
asv run --python=same --quick                  # current env, 1 repeat (smoke test)
```
Benchmark naming: `time_*`, `timeraw_*`, `mem_*`, `peakmem_*`, `track_*`. It also supports `setup`, `setup_cache`,
and `params` ([docs](https://asv.readthedocs.io/en/latest/using.html)). It's the standard in the NumPy, SciPy, and pandas ecosystem. It builds
per-commit envs, which is slow but gives a real history.

### 3.6 Bencher

```bash
bencher run --adapter python_pytest --file results.json "pytest --benchmark-json results.json benchmarks/"
bencher run --adapter python_asv "asv run"
```
Bencher stores results and applies statistical **thresholds** (t-test, z-score, percentage, IQR families; see
[thresholds](https://bencher.dev/docs/explanation/thresholds/)) per branch/testbed. It's self-hostable. Use it to
keep pytest-benchmark but get history and alerting
([adapters](https://bencher.dev/docs/explanation/adapters/)).

### 3.7 timeit pitfalls

```bash
python -m timeit -s "x=list(range(1000))" "sum(x)"        # auto-loops; reports best of 5
```
- It reports the **minimum**, which is fine for "how fast can this be" but hides variance and GC effects. It
  disables GC during timing by default (`timeit` sets `gc.disable()`). Re-enable with `-s "import gc; gc.enable()"` if
  allocation-heavy.
- Constant folding and caching will fool you: `"x = 2**100"` is folded at compile time. Hoisting setup into the
  statement measures setup. Repeated identical inputs measure warm caches, `lru_cache`, and specialized
  bytecode. A single process gives one memory layout, so use pyperf for anything you'll claim in a PR.
- Microbenchmarks rarely predict app-level wins. Always confirm with the real workload.

### 3.8 Statistical rigor checklist (bake into agent prompts)

1. Same machine, same interpreter build, same deps (pin with a lockfile). Record `python -VV`,
   `pyperf metadata`, CPU model, and governor.
2. Use multiple processes (pyperf) and many rounds. Report the **median and IQR, or the mean ± stdev**, plus N.
3. Compare A and B **interleaved or back-to-back** on the same host. Never compare against a number from yesterday's
   CI runner.
4. Check significance (`pyperf compare_to`, Bencher t-test) and set a minimum effect size (≥2–5 %).
5. Use **varied, realistic inputs**, and not the exact inputs the test asserts on (anti-caching-hack).
6. Re-run the full test suite after every optimization. A benchmark should assert its result.
7. For CI gates on shared runners, prefer CPU simulation (CodSpeed) or instruction counts over wall time.

---

## 4. Async, I/O, web and DB

### 4.1 asyncio
- **pyinstrument** (async_mode on by default) for request-level async profiles. **Tachyon**
  `--async-aware [--async-mode=all]` on 3.15. **Scalene** shows per-line `await` time and concurrency.
- **Python 3.14+:** `python -m asyncio ps <PID>` and `python -m asyncio pstree <PID>` print the live task tree of
  a running process ([What's New 3.14](https://docs.python.org/3/whatsnew/3.14.html)), which helps with stuck or slow tasks.
- `PYTHONASYNCIODEBUG=1` / `asyncio.run(main(), debug=True)` / `loop.slow_callback_duration = 0.05` logs
  callbacks that block the loop for more than 50 ms. This is the #1 async perf bug: sync I/O or CPU work in a coroutine.
  Fix it with `await asyncio.to_thread(fn)` or a process pool.
- **aiomonitor** (0.7.1, last release 2024-11) is an in-process telnet/REPL plus web UI for `ps`, `where`, and `cancel`.
  It still works, but the 3.14 `python -m asyncio ps` covers the basic need without code changes.
- yappi with `set_clock_type("wall")` gives per-coroutine wall time.

### 4.2 Web frameworks
- **Django:** django-debug-toolbar 8.0 (SQL panel with duplicate and similar query counts, plus a profiling panel),
  **django-silk** 5.6 (request/SQL recording, with optional cProfile per request via `SILKY_PYTHON_PROFILER=True`),
  and the pyinstrument middleware (`?profile`).
- **Flask:** `from werkzeug.middleware.profiler import ProfilerMiddleware; app.wsgi_app =
  ProfilerMiddleware(app.wsgi_app, profile_dir="prof", restrictions=[30])`. This writes `.prof` per request.
  pyinstrument's before/after-request recipe also works.
- **FastAPI/Starlette:** pyinstrument HTTP middleware gated on a query param or header. Note that sync `def` endpoints
  run in a threadpool, so pyinstrument's async middleware only sees async routes. Use py-spy/Tachyon `-a` for
  threadpool work.

### 4.3 SQL query counts / N+1
- **Tests (best for agents, deterministic):**
  - Django: `with self.assertNumQueries(3):`, `django.test.utils.CaptureQueriesContext(connection)`, and
    pytest-django's `django_assert_num_queries(3)` / `django_assert_max_num_queries(5)` fixtures.
  - SQLAlchemy 2.x: count via events:
    ```python
    from sqlalchemy import event
    count = 0
    @event.listens_for(engine, "before_cursor_execute")
    def _c(conn, cursor, stmt, params, ctx, many):
        global count; count += 1
    ```
    Set `lazy="raise"` on relationships, or use `options(raiseload("*"))` in tests, so that any lazy load becomes an error
    (N+1 becomes a test failure). Use `selectinload()`/`joinedload()` for the fix. `create_engine(..., echo=True)` or
    `logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)` gives quick visibility.
- Django fixes: `select_related` (FK/1-1, JOIN) and `prefetch_related` (M2M/reverse FK). django-auto-prefetch for
  zero-config FK prefetch. `QuerySet.explain()`. `.only()`/`.values_list()` for wide rows. `bulk_create`/`bulk_update`,
  `iterator(chunk_size=...)`.
- **nplusone** (last release 2018) is unmaintained. Treat it as legacy. Newer detectors exist
  (django-query-capture, django-queryguard-n1). Their maturity is **unverified**, so prefer query-count assertions.

### 4.4 Tracing and continuous profiling
- **OpenTelemetry:** `pip install opentelemetry-distro opentelemetry-exporter-otlp && opentelemetry-bootstrap -a install`,
  then `opentelemetry-instrument python app.py`. This auto-instruments Django, Flask, FastAPI, requests, httpx,
  SQLAlchemy, psycopg, and more. Spans show *which* request or DB call is slow. Profilers show *why*.
  The **OTel Profiles signal entered public alpha in March 2026**. There's no Python SDK profiling API yet. Python on Linux
  is covered by the eBPF profiler (collector component). Not for critical prod yet
  ([OTel blog](https://opentelemetry.io/blog/2026/profiles-alpha/)).
- **Pyroscope:** `pip install pyroscope-io`, then
  `pyroscope.configure(application_name="svc", server_address="http://pyroscope:4040", sample_rate=100,
  oncpu=True, gil_only=True, tags={"region": "x"})`. It's py-spy-based. Call `configure()` **after fork** (gunicorn
  `post_fork`). Use `pyroscope.tag_wrapper({...})` for per-endpoint labels. There's no memory profiling on free-threaded builds.
  Grafana Alloy's eBPF mode needs no code changes
  ([docs](https://grafana.com/docs/pyroscope/latest/configure-client/language-sdks/python/)).

---

## 5. Anti-patterns and high-leverage fixes (ordered by typical payoff)

1. **Algorithmic/data-structure** (10–1000×): `x in list` inside a loop → `set`/`dict`. Nested-loop joins →
   dict index. Repeated `list.pop(0)`/`insert(0)` → `collections.deque`. Sorting to get the top-k →
   `heapq.nlargest`. Repeated `sorted()` on insert → `bisect.insort`. Recomputing aggregates → incremental.
2. **I/O and DB** (often the real bottleneck): N+1 queries, per-row commits, no connection pooling, sync HTTP
   in loops (→ `httpx.AsyncClient` with bounded concurrency, or a session with keep-alive), reading files line by line with
   Python parsing where `pyarrow`/`polars` readers exist, missing indexes (`EXPLAIN ANALYZE`).
3. **Vectorize** numeric/tabular loops: numpy ufuncs/broadcasting, pandas vectorized ops (no `iterrows`/
   `apply(axis=1)`), **polars** lazy API (`pl.scan_parquet(...).filter(...).group_by(...).collect()`), which is
   multithreaded with query optimization. Watch for hidden copies (Scalene "copy volume") and
   object-dtype columns.
4. **Caching:** `functools.cache`/`lru_cache(maxsize=...)` for pure functions, `cached_property`. Beware unbounded
   caches on methods (memory leak), mutable-arg results, and **caching to game a benchmark** (Section 7).
5. **Interpreter-level micro-wins** (usually 1.1–2×, only in proven hot loops): hoist attribute and global lookups
   (`append = out.append`), use comprehensions over `for`+`append`, `"".join(parts)` instead of `+=` in loops, precompile
   regexes (`re.compile` at module level; the `re` cache has 512 entries), `str` methods over regex where possible,
   `itertools`/builtins (`sum`, `map`, `any`) over manual loops, avoid `try/except` for control flow in very
   hot paths (zero-cost try in 3.11+ makes the non-raising path cheap, but raising is still expensive), avoid
   `**kwargs`/deep call chains in the inner loop, use local variables. Since 3.11, the specializing adaptive interpreter
   rewards **type-stable** code. Mixing types at one site de-optimizes it (Tachyon `--opcodes` shows
   specialization).
6. **Generators vs lists:** generators save memory for streaming and early exit (`any()`, `next()`). Lists are faster when
   you iterate multiple times or need `len`. Don't materialize `list(range(n))` just to loop.
7. **`__slots__`** / `@dataclass(slots=True)`: smaller objects (no `__dict__`) and faster attribute access. Matters
   with millions of instances. `NamedTuple` and `array`/numpy structured arrays for bulk records.
8. **Serialization:** `orjson`/`msgspec` vs `json` (often 3–10×), `msgspec.Struct` vs pydantic in hot paths
   (pydantic v2 core is Rust and fast, but validation still costs). Avoid `copy.deepcopy` in loops.
9. **Concurrency model:**
   - I/O-bound → `asyncio` or threads.
   - CPU-bound pure Python → `multiprocessing`/`ProcessPoolExecutor` (pickling cost; on macOS the default start method
     is `spawn`, so the import cost is paid per worker), or `concurrent.futures.InterpreterPoolExecutor` (3.14,
     PEP 734 subinterpreters, **unverified** maturity for real workloads).
   - **Free-threaded 3.14t is officially supported (PEP 779, Final).** The single-thread penalty is about 5–10 %
     ([What's New 3.14](https://docs.python.org/3/whatsnew/3.14.html)). Threads give real CPU parallelism if all C
     extensions declare free-thread support (otherwise the GIL is re-enabled at import, which you can check with
     `sys._is_gil_enabled()`). Install with `uv python install 3.14t` and force with `python -X gil=0`. 3.15 adds the `abi3t` stable ABI for
     free-threaded extensions (PEP 803).
   - numpy, polars, and other native code releases the GIL, so threads already parallelize those.
10. **Compile the hot kernel:**
    - **mypyc** (ships with mypy 2.4): compiles type-annotated modules, often 2–5× for typed pure-Python code
      (black and mypy use it). Low effort if the code is already typed.
    - **Cython 3.3**: `cdef` types and `nogil` for C speed. Pure-Python mode lets you keep `.py` files.
    - **Rust via PyO3 0.29 + maturin 1.15**: `maturin new -b pyo3`, `maturin develop --release`. The best choice for
      complex kernels, safe parallelism (rayon), and free-threaded support.
    - **numba 0.68** `@njit` for numeric loops over numpy arrays (JIT warmup cost on the first call).
11. **CPython JIT status:** 3.13 and 3.14 shipped an experimental copy-and-patch JIT (often no faster). The 3.14 Windows and macOS
    python.org binaries include it, off by default (`PYTHON_JIT=1` to enable; **env var not re-verified for
    3.15**). **3.15**: the upgraded JIT (new tracing frontend, register allocation, refcount elimination) gives a
    **7–8 % geomean speedup on x86-64 Linux and 11–12 % on AArch64 macOS** vs the best interpreter, ranging from −15 % to +100 % per
    benchmark ([What's New 3.15](https://docs.python.org/3.15/whatsnew/3.15.html)). It's still experimental, and free-threading
    support is planned. PEP 836 (Draft) targets a supported JIT with ≥20 % geomean by 3.17. **Upgrading CPython
    is itself a perf fix**: 3.11 was about 25 % faster than 3.10, and the 3.14 tail-calling interpreter adds 3–5 % with
    supported compilers.
12. **Static lint for perf smells:** `ruff check --select PERF,C4,SIM,UP,FURB` (PERF = perflint port: e.g.
    `PERF401` use comprehension, `PERF203` try in loop, `PERF102` dict items misuse). Cheap, deterministic,
    and agent-friendly. Treat it as hints, not proof.

---

## 6. Import time and CLI startup

```bash
python -X importtime -c "import mypkg.cli" 2> import.log       # stderr: self(us) | cumulative(us) | module
PYTHONPROFILEIMPORTTIME=1 mycli --help 2> import.log
python -X importtime=2 -c "import mypkg"                        # 3.14+: also shows cached (already-loaded) imports
sort -t'|' -k2 -n import.log | tail -20                         # top cumulative (agent-friendly)
tuna import.log                                                 # browser icicle (tuna 0.5.15)
python -m pyperf command -- python -m mypkg.cli --version       # rigorous startup timing
hyperfine --warmup 3 'mycli --help'                             # alternative wall-clock CLI timer
```
Fixes:
- Defer heavy imports (pandas, numpy, torch, boto3, pydantic models, requests) into the functions that use them.
- Avoid import-time work (regex compiles of huge patterns, reading config, network, building big tables).
- Use lazy `__getattr__` in package `__init__` (PEP 562).
- Avoid importing all subcommands for `--help` (click/typer lazy groups).
- Check `-X frozen_modules`/`.pyc` availability (read-only installs without bytecode recompile every run; use
  `python -m compileall`).
- **3.15: PEP 810 explicit lazy imports (Final):** `lazy import json`, `lazy from pathlib import Path`, module-level
  `__lazy_modules__ = [...]`, global `-X lazy_imports=all` / `PYTHON_LAZY_IMPORTS`, and `sys.set_lazy_imports_filter()`.
  Measure with `-X importtime` before and after. How lazy imports render in importtime output is **unverified**.
- `-X importtime` output may be garbled in multithreaded apps
  ([cmdline docs](https://docs.python.org/3/using/cmdline.html)). Startup also includes `site` and `.pth` processing
  (editable installs and big site-packages add cost). Compare with `python -I -S -c pass`.

---

## 7. LLM/agent-driven performance optimization: research findings (2024–2026)

| Work | What | Headline result / lesson |
|---|---|---|
| **PIE**: Learning Performance-Improving Code Edits (ICLR 2024) [paper](https://arxiv.org/abs/2302.07867) | 77K C++ pairs, timed in **gem5 simulator** | Real-hardware timing produced "phantom" improvements from noise, so they used a deterministic simulator. **Lesson: noisy measurement fools optimizers; use instruction-count/simulation or rigorous stats.** |
| **ECCO** (EMNLP 2024) [paper](https://arxiv.org/abs/2407.14044) | Python efficiency benchmark | **No method improved efficiency without sacrificing functional correctness.** Execution feedback helps correctness, while NL feedback helps find optimization strategies. |
| **GSO** (2025, updated through 2026-09) [site](https://gso-bench.github.io/), [paper](https://arxiv.org/abs/2505.23671) | 102 tasks, 10 codebases, 5 languages. Opt@1 = ≥95 % of expert speedup + tests pass | Initially **under 5 %** success. Failure modes: **lazy optimization**, **bad bottleneck localization**, low-level languages. Added an LLM **Hack Detector** (Nov 2025) after agents **cached outputs for repeated benchmark inputs** (global caches, `lru_cache`) and did "lazy evaluation" that skipped real work. Sep 2026 prompting change: ask models to *keep measuring and improving after the first speedup*. Current leaderboard numbers: **unverified** (page is JS-rendered). |
| **SWE-Perf** (Jul 2025) [paper](https://arxiv.org/abs/2507.12415) | 140 instances, 9 Python repos | Expert +10.85 % vs best agent (OpenHands + Claude 3.7 Sonnet) **+2.26 %**. Agents occasionally beat the expert on specific repos (sklearn). |
| **SWE-fficiency** (ICML 2026) [paper](https://arxiv.org/abs/2511.06090), [OpenHands blog](https://www.openhands.dev/blog/20260216-swefficiency-benchmark) | 498 tasks (numpy, pandas, scipy, ...), real workloads | Agents reach **under 0.23× expert speedup**. They pick the **wrong file/function about 71 % of the time**. **"Satisficing"**: they stop after the first small gain. **"Convenience bias"**: input-specific hacks, ad-hoc caching, and monkey patches instead of structural fixes (e.g. moving work to compiled backends). Correctness breaks are common. |
| **PerfAgent** (Jul 2026) [paper](https://arxiv.org/abs/2607.19653) | Profiler-guided, verifier-in-the-loop wrapper around an off-the-shelf agent | Expert-matching patches go from **19.6 % → 39.2 % on GSO** and **26 % → 74 % on SWE-fficiency-Lite** over OpenHands+GPT-5.1. It beats oracle best-of-5 at lower cost. **Gains come from better feedback (profiler evidence instead of timing alone) rather than more sampling.** Agents otherwise miss hotspots hidden behind abstraction layers and native extensions. |
| **SWE-Pro / "Evaluating LLMs on Real-World Software Performance Optimization"** (Jun 2026) [paper](https://arxiv.org/abs/2606.25530) | 102 expert optimizations, runtime + peak memory + time-weighted memory, noise-aware | LLM runtime gains are "negligible" and **memory optimizations are nearly non-existent**. Experts achieve 15.5× aggregate speedup and 171× peak-memory reduction. |
| **Scalene AI proposals** ([repo](https://github.com/plasma-umass/scalene)) | Profiler sends hot lines plus context to an LLM | Profiler-scoped prompts focus the LLM on measured hotspots. Suggestions still need verification. |
| **AlphaEvolve-style loops**: OpenEvolve, CodeEvolve ([CodeEvolve](https://arxiv.org/abs/2510.14150)) | LLM mutations + evolutionary search (MAP-Elites, islands) + automatic evaluator | They work when an **automatic, trustworthy fitness function** exists (benchmark + correctness check). Evaluator quality bounds the results, and a weak evaluator gets exploited. |

**Distilled rules for a coding agent (encode in the skill):**
1. **Never optimize without a profile.** Run a sampler first, and include the top-N hot frames (collapsed stacks/JSON) in
   your reasoning. Localization is the #1 failure mode (about 71 % wrong-target rate in SWE-fficiency).
2. **Follow hotspots through abstraction and native boundaries.** Use `--native` (Linux py-spy/Tachyon/memray),
   Scalene's Python-vs-native split, and `perf -X perf`. Bottlenecks often live in how Python *calls* a library
   (per-element calls, copies, dtype=object).
3. **Correctness gate before speed claims.** Run the full relevant test suite and assert outputs in benchmarks. Use
   differential testing (old vs new on randomized inputs: `hypothesis`) for rewritten kernels.
4. **No benchmark gaming:** don't add caches keyed on the benchmark's inputs, don't skip work lazily, and don't special-case
   sizes or values in the workload. Benchmark on **inputs different from the ones you inspected**. If you add a cache,
   justify it from production access patterns and bound its size.
5. **Don't satisfice.** After the first win, re-profile. The hotspot moves. Stop when the profile is flat or the
   remaining time is in irreducible I/O/native work, and report the remaining breakdown.
6. **Prefer structural fixes** (algorithm, batching/vectorization, moving loops into numpy/polars/Rust) over micro-hacks
   and monkey patches. Keep the diff maintainable.
7. **Report with statistics:** before/after medians, variance, N, significance (pyperf `compare_to`), machine info,
   and **memory too** (agents ignore memory; check peak RSS or memray stats for regressions).

---

## 8. Recommended defaults for the skill (macOS dev + Linux CI)

```bash
# install-free invocations via uv (no project pollution)
uvx pyinstrument -r json -o prof.json script.py          # macOS default (no sudo)
uvx --from scalene scalene run --cpu-only -o scalene.json script.py
sudo uvx py-spy record -f speedscope -o p.json -- .venv/bin/python script.py   # macOS needs sudo; not /usr/bin/python3
uvx py-spy record -f raw -o stacks.txt -- python script.py                     # Linux CI, no root needed
python3.15 -m profiling.sampling run --collapsed -o stacks.txt script.py      # 3.15 projects
uvx --from memray memray run -o m.bin script.py && uvx --from memray memray stats --json -o m.json m.bin
uv run --with pyperf python -m pyperf timeit -s "..." "..." -o new.json
python -X importtime -c "import pkg" 2>&1 | sort -t'|' -k2 -n | tail -15
```
Note: `uvx` tools run in their own env. In-process profilers (pyinstrument, Scalene, memray, line_profiler) must
import *your* project's deps, so prefer `uv run --with pyinstrument pyinstrument ...` inside the project.

CI layout:
- **PR gate:** CodSpeed simulation (or pytest-benchmark `--benchmark-compare-fail=min:10%` on a dedicated runner).
  Add pytest-memray `limit_memory` on key paths and query-count assertions for DB code.
- **Nightly:** asv or Bencher history.
- **Prod:** Pyroscope/OTel eBPF.
