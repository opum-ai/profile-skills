# Python benchmark harnesses

| Situation | Tool (ADR-0006: tools collect, perfkit decides) |
|---|---|
| Rigorous A/B of a function or snippet; across interpreters | **pyperf** (multi-process, calibrated) → `perfkit compare a.json b.json` |
| Whole command | `perfkit abtest` (interleaved, paired) or `perfkit abtest --engine hyperfine`; `pyperf command` |
| Benchmarks living in the pytest suite | **pytest-benchmark** (assert the result inside) |
| Low-noise CI regression gate on shared runners | **pytest-codspeed** (CPU simulation; Linux) |
| History across commits, bisecting | **asv** |
| Quick sanity check | `python -m timeit`, with its caveats |

## pyperf

```bash
uv run --with pyperf python -m pyperf timeit -s "import mod; d = mod.make_data(10_000)" "mod.f(d)" -o .perf/<c>/base.json
python -m pyperf timeit --rigorous ...                 # more processes/values
python -m pyperf command -o .perf/<c>/cli.json -- python -m mycli --help
python -m pyperf compare_to .perf/<c>/base.json .perf/<c>/new.json --table -G --min-speed=2
python3 $PK compare .perf/<c>/base.json .perf/<c>/new.json --min-effect 0.02   # same files, bootstrap CI verdict
```
Script API for complex setups:
```python
import pyperf
runner = pyperf.Runner()
runner.bench_func("dedupe-10k", mod.dedupe, data)    # no prints in workers
```
- pyperf spawns 20 worker processes by default and averages over memory layouts and hash
  seeds. `compare_to` uses a t-test, `check` warns when stdev exceeds 10% of the mean, and
  `system tune` works on Linux only.
- To A/B two checkouts, run the same pyperf command from each worktree (or pass
  `--python=../wt-incumbent/.venv/bin/python`). Alternate the order, so each arm runs both
  first and second.

## pytest-benchmark

```python
def test_dedupe_10k(benchmark):
    data = make_data(10_000, seed=1)
    result = benchmark(dedupe, data)
    assert result == expected_dedupe(data)       # the benchmark proves it did the work
```
```bash
pytest benchmarks/ --benchmark-only --benchmark-json=.perf/<c>/b.json --benchmark-save-data   # raw samples for perfkit
pytest benchmarks/ --benchmark-only --benchmark-autosave
pytest benchmarks/ --benchmark-only --benchmark-compare --benchmark-compare-fail=min:10%
pytest -p no:benchmark  # or --benchmark-disable in normal runs: executes once, no timing
```
- `--benchmark-compare-fail` compares against **one** saved run, with no significance test.
  On shared CI, gate on `min` with a generous threshold, or use perfkit/CodSpeed.
- Don't benchmark under pytest-xdist or coverage.
- `pedantic(setup=...)` keeps setup out of the timing.

## pytest-codspeed

```bash
uv add --dev pytest-codspeed
pytest benchmarks/ --codspeed          # local: runs and validates (timing only in CI with the action)
```
- It uses the same `benchmark` fixture and `@pytest.mark.benchmark` API as
  pytest-benchmark.
- **CPU simulation** (Valgrind-based instruction and cache counting) is near-deterministic,
  but it **excludes syscalls and I/O**. Use walltime mode on dedicated runners for I/O-bound
  or threaded code.
- See perf-ci for the workflow.

## asv

```bash
asv continuous --factor 1.1 --split main HEAD     # fail if >10% slower
asv compare main HEAD --sort ratio
asv find v1.0..main time_parse                    # bisect a regression
```
Benchmarks are `time_*`, `peakmem_*` and `track_*` functions with `params`. asv builds an
environment per commit, which is slow but gives real history. It's the standard in the
scientific-Python ecosystem.

## timeit pitfalls

- It reports the **best** of its repeats, and **disables GC** during timing. That hides
  allocation cost; add `-s "import gc; gc.enable()"`.
- Literal inputs get constant-folded (`2**100`). Repeated identical inputs measure warm
  caches (`lru_cache`, `re` cache, specialized bytecode).
- It runs one process, so you get one memory layout. Use pyperf for anything you'll claim.

## Data generation

Generate inputs with a fixed seed **outside** the timed region. Use realistic distributions
(duplicates, skew, sizes). Keep a different seed for the hold-out. Never benchmark on the
exact inputs the tests assert on.
