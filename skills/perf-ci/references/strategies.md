# CI performance strategies

## 1. Same-runner interleaved A/B (default; perfkit suite)

Build base and head in one job and measure both, interleaved, on the same runner. Laaber
et al. showed that randomized interleaving on the same cloud instance detects slowdowns of
≤10% reliably, where comparisons across instances can't. Variance between runners (CPU
model, neighbors) cancels out because both arms see the same runner.

```bash
perfkit suite --policy perf-policy.toml --policy-ref "$BASE_SHA" --base ../base --head . --out-dir ../perf-ci
perfkit gate  --policy perf-policy.toml --policy-ref "$BASE_SHA" --compare ../perf-ci/comparisons.json --metrics ../perf-ci/metrics.json
```

**Choosing tolerances from noise.** On the target runner class, run the suite with the same
checkout as both arms, 3 times:
```bash
perfkit suite --policy perf-policy.toml --base . --head . --out-dir /tmp/aa1   # repeat → aa2, aa3
jq '.comparisons[] | {name, change_pct, ci: .ratio_ci}' /tmp/aa*/comparisons.json
```
- Set `min_effect` to roughly the largest |change_pct| an A/A run produces.
- Set `max_regression` to at least 2× that, which is typically 5–10% on GitHub-hosted runners.
- If a benchmark's A/A spread exceeds 10%, fix the benchmark: make the workload longer, the
  input fixed, and remove I/O. Otherwise move it to instruction counts or nightly.

## 2. Instruction counts (low-noise proxy)

- **CodSpeed simulation** runs Valgrind-based instruction and cache simulation, once per
  benchmark. It is near-deterministic, but **excludes syscalls and I/O**, and needs Linux.
  - Python: `pytest-codspeed`, with `CodSpeedHQ/action@v5` and `mode: simulation`.
  - JS: `@codspeed/vitest-plugin` (Vitest ≤4; Vitest 5 support was pending as of
    Sep 2026) or `@codspeed/tinybench-plugin`.
  - Its walltime mode needs CodSpeed's bare-metal runners.
- **DIY:**
  - `perf stat -e instructions:u -x, -r 5 cmd` (Linux; needs `perf_event_paranoid ≤ 1`;
    `sudo sysctl` works on GitHub Ubuntu runners).
  - `valgrind --tool=cachegrind --cache-sim=no cmd`: the `Ir` line is the instruction count.
  - Write the count with a `[[metric]]` command and budget it, or A/B it with tolerances
    of 0.5–2%.
- **Caveats:**
  - Instruction counts ignore memory latency, parallelism and I/O. A threaded change can add
    instructions and still reduce wall time.
  - glibc picks different code paths on different CPUs, so even instruction counts shift
    between runner CPU models. Pin the runner image, and record the CPU.
  - Confirm user-facing wins with wall time.

## 3. History and trend tools (main branch)

| Tool | Use |
|---|---|
| **Bencher** (`bencher run --adapter shell_hyperfine \| python_pytest \| json ...`) | statistical thresholds over history (t-test, z-score, IQR) or relative same-job mode; self-hostable |
| **github-action-benchmark** (`tool: customSmallerIsBetter`, `alert-threshold: '120%'`) | history in gh-pages, charts, alert comments; simple ratio vs. the previous run, which is noisy on shared runners |
| **asv** (`asv continuous --factor 1.1 main HEAD`, `asv find`) | scientific Python; builds per commit; bisects regressions |
| **CodSpeed** dashboard | history of the simulation counts per branch |

To feed github-action-benchmark from perfkit:
```bash
jq '[.comparisons[] | {name, unit: "s", value: .candidate.median}]' perf-ci/comparisons.json > bench.json
```

## 4. Budgets as tests (deterministic counts)

These are cheaper and less flaky than timing:
- **SQL query counts:** `django_assert_max_num_queries(5)`, or a SQLAlchemy event counter
  with an assert.
- **exec/fork counts for shell scripts:** `strace -f -qq -e trace=execve` count on Linux.
- **bytes shipped:** size-limit, or a `[[metric]]` on `dist/` file sizes.
- **allocations / peak memory:** pytest-memray `@pytest.mark.limit_memory("50 MB")`.
- **complexity:** `perfkit scaling --max-exponent 1.3` on a generated input. It is stable
  across machines because it is a ratio.

Put counts that belong next to the code in the test suite, under test-skills' admission
rules. Put the rest in `[[metric]]`/`[[budget]]`.

## 5. Policy integrity

- `--policy-ref <base sha>` reads `perf-policy.toml` from the base revision. Policy changes
  take effect only after they merge, in their own reviewed PR. This mirrors test-skills'
  `tmx gate --base`.
- Benchmarks and workloads live in the repo. A PR that edits both a benchmark and the code
  it measures should be flagged by review (perf-measure review mode checks this). Consider CODEOWNERS on
  `perf-policy.toml` and `benchmarks/`.
- At R4/R5, approvals come from the code host's review record, never a commit trailer.
