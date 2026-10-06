# Profiling Python

Versions as of Oct 2026: py-spy 0.4.2 (Python ≤3.14), pyinstrument 5.1, Scalene 2.3,
memray 1.20, line_profiler 5.0, yappi 1.7, VizTracer 1.1, CPython 3.15 (final 2026-10-09;
it ships the `profiling` package from PEP 799).

## Contents
1. Choosing (decision table)
2. CPU / wall-clock samplers
3. Deterministic: cProfile and line_profiler
4. Async, threads, timelines
5. Startup and import time
6. Profiling tests and web apps
7. Native code and `perf`
8. Running tools without polluting the project

## 1. Choosing (ADR-0006: best-of-breed, installed on demand)

| Need | Default | Notes |
|---|---|---|
| Where does time go | **py-spy** `record -f speedscope -o .perf/<c>/p.speedscope.json -- python script.py` | 1.02× overhead, out-of-process. Install: `uv tool install py-spy`. `--idle` adds waiting time; `--subprocesses` follows children |
| ...on macOS | py-spy **needs root** there and can't profile `/usr/bin/python3` | check `sudo -n true`. If it fails, ask the user to run the exact command with the `!` prefix: `! sudo py-spy record -f speedscope -o .perf/<c>/p.json -- .venv/bin/python script.py`. If they decline, fall back to Scalene `--cpu-only` (1.02×) or pyinstrument (1.69×, in-process) and say so in the report |
| Line-level CPU, memory and Python-vs-native split, copy volume | **Scalene** `uv run --with scalene scalene run --cpu-only -o .perf/<c>/scalene.json script.py` | drop `--cpu-only` for memory (1.32×); `scalene view --cli` |
| Allocations, peak, leaks | **memray** `uv run --with memray memray run -o .perf/<c>/m.bin script.py` | `memray stats --json`, `flamegraph --leaks` with `PYTHONMALLOC=malloc` (`memory.md`) |
| Exact call counts | cProfile `python -m cProfile -o .perf/<c>/p.prof` | 1.73× and distorts shares; use it for counts |
| Which line in a named function | line_profiler `kernprof -l -v` | 2.21×; only after a sampler named the function |
| Threads / asyncio attribution | py-spy `--threads --idle`; yappi (`set_clock_type("wall")`) | cProfile mis-attributes both |
| Python 3.15+ | `python -m profiling.sampling run --collapsed` | same-minor-version only; attach needs root on macOS |
| Timeline / ordering | VizTracer → Perfetto | not aggregates |

`perfkit hotspots` reads:
- pstats from cProfile, `pyinstrument -r pstats` and yappi `save(type="pstat")`;
- speedscope from py-spy and pyinstrument;
- folded stacks from `py-spy -f raw` and `profiling.sampling --collapsed`.

Scalene's JSON is read directly by you: per-line `n_cpu_percent_python`, `n_cpu_percent_c`, `n_malloc_mb`,
`n_copy_mb_s`.

## 2. Samplers

### py-spy (default)
```bash
uv tool install py-spy                     # user-level; no project change
py-spy record -f speedscope -o .perf/<c>/p.json --rate 250 -- .venv/bin/python script.py
py-spy record -f raw -o .perf/<c>/p.folded --idle --subprocesses -- python script.py   # waiting + children
py-spy record --native -- python script.py         # C-extension frames: Linux only
py-spy dump --pid 1234 --locals                    # hung process (root)
```
- Linux: launching a child needs no root. Attaching needs root or `CAP_SYS_PTRACE` (Docker: `--cap-add SYS_PTRACE`).
- macOS: root always; no `--native`; not `/usr/bin/python3`. Use the uv or Homebrew interpreter.
- No Python 3.15 support in 0.4.2. Use Tachyon there.

### Scalene (line level)
```bash
uv run --with scalene scalene run --cpu-only -o .perf/<c>/scalene.json script.py
uv run --with scalene scalene run --profile-only src/ -o .perf/<c>/scalene.json script.py --- --arg 1
scalene view --cli
```
- It splits time per line into Python, native and system. Use that to tell an interpreter-bound loop from a slow
  library call. "Copy volume" flags hidden numpy↔Python conversions.
- Its 2.x CLI is `run` / `view`; the old `scalene --cli --json` flags were reorganized.
- It runs in-process (`uv run --with` inside the project, not `uvx`), so it needs the project's dependencies.

### pyinstrument (fallback when py-spy can't run)
```bash
uv run --with pyinstrument pyinstrument -r speedscope -o .perf/<c>/p.speedscope.json script.py args
pyinstrument -m pytest tests/test_slow.py
```
- In-process, no root, async-aware.
- 1.69× overhead skews shares in call-heavy code. Confirm the top frame with cProfile counts or a py-spy run on Linux.

### Tachyon: `python -m profiling.sampling` (3.15+)
```bash
python -m profiling.sampling run --collapsed -o .perf/<c>/stacks.folded script.py
python -m profiling.sampling run --mode=wall -a script.py
python -m profiling.sampling run --binary -o .perf/<c>/base.bin script.py      # later: --diff-flamegraph base.bin
```

## 3. Deterministic profilers

```bash
python -m cProfile -o .perf/<c>/p.prof script.py args       # or -m pkg.module
python - <<'EOF'
import pstats; s = pstats.Stats(".perf/<c>/p.prof"); s.sort_stats("tottime").print_stats(15); s.sort_stats("cumulative").print_stats(15)
EOF
```
- Use cProfile for "**why is `normalize()` called 1.2M times?**". Its call counts are exact.
  Its overhead makes cheap, frequently called functions look 2× worse than reality, so take
  shares from a sampler.
- It sees the main thread only, and isn't async-aware (the event loop dominates).
- `pytest --benchmark-cprofile=cumtime` (pytest-benchmark) and `asv profile` reuse it.

line_profiler (only for the 1–5 functions a sampler already named):
```bash
uv run --with line_profiler kernprof -l -v -p mypkg.core script.py   # -p: profile modules without @profile
python -m line_profiler -rmt script.py.lprof
```

## 4. Async, threads, timelines

- **The #1 async bug is blocking the loop.** Run with `PYTHONASYNCIODEBUG=1` (or
  `asyncio.run(main(), debug=True)` plus `loop.slow_callback_duration = 0.05`) to log
  callbacks over 50 ms. Fix with `await asyncio.to_thread(fn)`, or a process pool for CPU work.
- **Sequential awaits** of independent work show as wall time with idle CPU. Use
  `asyncio.gather` / `TaskGroup` with a semaphore bound.
- **3.14+:** `python -m asyncio ps <PID>` and `python -m asyncio pstree <PID>` show live task
  trees.
- **yappi:**
  ```python
  import yappi; yappi.set_clock_type("wall"); yappi.start()
  run(); yappi.stop()
  yappi.get_func_stats().save(".perf/<c>/y.prof", type="pstat")
  ```
  `get_thread_stats()` gives per-thread totals.
- **VizTracer:** `viztracer -o trace.json -- python app.py` (Chrome trace JSON). Its default
  circular buffer holds 1M entries.

## 5. Startup and import time

```bash
python -X importtime -c "import mypkg.cli" 2> .perf/<c>/import.log
sort -t'|' -k2 -n .perf/<c>/import.log | tail -20          # top cumulative µs
python -X importtime=2 -c "import mypkg"              # 3.14+: also cached imports
hyperfine -N --warmup 3 'python -m mypkg.cli --version'   # or perfkit abtest
python -I -S -c pass                                   # interpreter floor without site
```
Fixes:
- defer heavy imports (pandas, numpy, torch, boto3, pydantic models) into the functions
  that use them;
- use PEP 562 module `__getattr__`, or 3.15 `lazy import` (PEP 810);
- use lazy click/typer subcommand groups;
- no work at import time (big regex compiles, config reads, network calls);
- check `.pyc` can be written.

## 6. Tests and web apps

- **A slow test suite:**
  - `pytest --durations=25` first;
  - then `pyinstrument -m pytest tests/test_slow.py`;
  - `-p no:cacheprovider` and running without xdist make profiles readable;
  - fixture setup cost shows as `setup` in `--durations`.
- **Django:**
  - pyinstrument middleware (`pyinstrument.middleware.ProfilerMiddleware`, `?profile`);
  - django-silk (`SILKY_PYTHON_PROFILER=True`);
  - debug-toolbar SQL panel (duplicate queries).
- **Flask:** `werkzeug.middleware.profiler.ProfilerMiddleware(app.wsgi_app, profile_dir=".perf/<c>/req")`
  writes one `.prof` per request.
- **FastAPI/Starlette:** pyinstrument HTTP middleware gated on a header. Sync `def`
  endpoints run in a threadpool, which async middleware doesn't see; use py-spy `--idle`
  for those.
- **DB / N+1:** see `services.md`. Count queries; don't profile them.

## 7. Native code and `perf` (Linux)

```bash
python -m sysconfig | grep HAVE_PERF_TRAMPOLINE
perf record -F 999 -g -o perf.data python -X perf script.py       # 3.12+, frame pointers (default in 3.15)
perf script -i perf.data | stackcollapse-perf.pl > .perf/<c>/p.folded  # → perfkit hotspots
```
On macOS use `samply record --save-only` (see `native.md`). Python frames may not be
symbolized; pair it with py-spy or pyinstrument.

When the hot frame is a C-extension call (numpy, regex, json), the fix is usually in **how
Python calls it**: per-element calls, `dtype=object`, copies, or many small calls. It is
rarely in the library itself. Fold library frames (`--project-root`) to find the calling line.

## 8. Running tools without polluting the project

- **Out-of-process tools** (py-spy) can come from `uvx`, which leaves the project untouched:
  `uvx py-spy record -f raw -o p.folded -- .venv/bin/python script.py`.
- **In-process tools** need the project's environment: `uv run --with pyinstrument ...`,
  or `pip install` into a throwaway venv that also has the project installed.
- **Don't add profilers to the project's dependencies** unless the user wants that.
