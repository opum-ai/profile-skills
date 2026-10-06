# perf-policy.toml schema

```toml
version = 1
rigor = "R3"                 # project default; R1..R5

[stats]
min_effect = 0.03            # verdict threshold (relative)
max_regression = 0.10        # default tolerance for tiers without their own
alpha = 0.05
min_runs = 10                # per arm; rigor raises it (R4: 20, R5: 30) unless set here
max_runs = 30                # suite tops up inconclusive results up to this (default 3× runs)

[[tier]]                     # first match wins
name = "hot-path"
benchmarks = ["report-*"]    # globs over [[benchmark]] names
paths = ["src/core/**"]      # documentation, perf-measure review scoping, and rigor lookup in test-policy.toml
rigor = "R4"
max_regression = 0.05

[[benchmark]]
name = "report-big"          # unique; used for tiers, history and metrics (bench.<name>.median_s)
cmd = "python -m app.report fixtures/big.csv"   # run in each checkout
cwd = "."                    # relative to each checkout
runs = 20
warmup = 2
max_runs = 40
prepare = "rm -rf .cache"    # before every measured run
timeout = 120
same_output = true           # head stdout must equal base stdout (when deterministic)
higher_is_better = false
min_effect = 0.03

[[metric]]                   # command printing one number (last token of stdout), run in head
name = "bundle.main_kb"
cmd = "..."
cwd = "."

[[budget]]
metric = "bundle.main_kb"    # from [[metric]], suite medians, or --metrics JSON files (flattened with dots)
max = 180                    # and/or min
unit = "kB"
required = true              # false: a missing measurement only warns
```

## How the gate decides

For each comparison, take its tier and its effective rigor = max(project, tier, `--rigor`).
Then:
- **fail** if the runs per arm are below `min_runs` (or the rigor floor);
- **fail** if the verdict is `regressed` or `below-threshold` *and* the slowdown exceeds the
  tier's `max_regression`;
- **fail** if the verdict is `inconclusive` and either the rigor is R4+ or the point
  estimate is worse than the tolerance (a possible regression hidden by noise);
- otherwise pass, with warnings for noise and small samples.

Budgets fail on `value > max` or `value < min`, and on a missing measurement when
`required`. Errors from `suite` (output differs, a metric command printed no number) fail
the gate too.

The exit code is 0 for PASS and 1 for FAIL. `--json` writes the full decision record for
artifacts.
