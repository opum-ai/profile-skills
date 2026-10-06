# perfkit command reference

`python3 perfkit.py <command> -h` for full options. Stdlib only (Python 3.9+); copy
`scripts/perfkit.py` + `scripts/perfkit/` into a repo (`tools/perfkit/`) to use in CI without
the plugin.

## doctor
`perfkit doctor [--python .venv/bin/python] [--json]` — installed profilers/harnesses per
ecosystem, Python modules importable by the given interpreter, bash major version, Node version,
and noise warnings (load average, battery / Low Power Mode, CPU governor/turbo, CI runner,
Apple Silicon core heterogeneity, bash < 5).

## abtest
```bash
perfkit abtest --a "<baseline cmd>" --b "<candidate cmd>" [--extra "<cmd>" ...] [--names base,cand,...]
               [--cwd-a DIR] [--cwd-b DIR] [--runs 20] [--warmup 2] [--prepare "<cmd>"] [--timeout S]
               [--require-same-output] [--all-metrics] [--no-counters] [--engine perfkit|hyperfine]
               [--hf-runs 3] [--hf-args "-N"] [--min-effect 0.02] [--unpaired] [-o ab.json]
```
- `--engine hyperfine` (ADR-0006): in each block, each arm gets one hyperfine burst of `--hf-runs` runs; the burst
  median is that block's paired sample. The raw hyperfine times are kept as `hyperfine_times`.
- Instruction counts (`instructions` per run) are recorded by default where the platform allows it without root:
  macOS `/usr/bin/time -l`, or Linux `perf stat -e instructions:u`. They are compared as a corroborating metric only.
  macOS counts the direct child process; for pipelines that is the shell.
- Comparisons from abtest are **paired** by block (Wilcoxon on per-block ratios).
- Runs blocks of all arms in shuffled order (seeded); first `--warmup` blocks discarded.
- Per run: wall time, child CPU time (user+sys), peak RSS, exit code, stdout SHA-256.
- Output check: `✓ stdout identical` / `⚠ OUTPUT DIFFERS` / `⚠ stdout varies between runs`
  (nondeterministic output — equivalence must be checked another way). `--require-same-output`
  exits 2 on a difference.
- Commands run through the shell; quote accordingly. Redirect bulky stdout you don't want hashed
  to a file and hash that file instead (`cmd > /tmp/o && shasum /tmp/o`).
- Prints the comparison(s) and writes `{"benchmarks": {...}, "meta": {...}, "output_check": {...},
  "comparisons": [...]}`.

## compare
```bash
perfkit compare ab.json [--baseline NAME]               # arms inside one file (abtest output)
perfkit compare base.json cand.json [--bench REGEX]     # matching benchmark names across two files
             [--min-effect 0.02] [--alpha 0.05] [--confidence 0.95] [--higher-is-better]
             [--json cmp.json] [--fail-on-regression]
```
Accepted inputs (auto-detected): perfkit JSON (abtest files are compared paired), mitata `run({format:'json'})`,
hyperfine `--export-json`, pyperf `-o`,
pytest-benchmark `--benchmark-json` **with `--benchmark-save-data`**, generic JSON holding raw
sample arrays (`samples|times|values|data|latencies` next to a `name`), text/CSV (one number per
line, or `name,value` rows). Raw samples are required; means alone can't be compared robustly.
Units are whatever the file uses; ratios are unit-free.

Output fields per comparison: `verdict`, `ratio` (median B / median A), `ratio_ci`, `speedup`
(1/ratio for lower-is-better), `change_pct`, `p_value` (Mann-Whitney U), `cliffs_delta`,
`baseline`/`candidate` summaries (n, min, q1, median, q3, max, p95, mean, stdev, cv, iqr_rel),
`warnings`, and `runs_needed` when inconclusive.

## hotspots
```bash
perfkit hotspots PROFILE [--top 15] [--by self|total|both] [--project-root .] [--fold REGEX]
                 [--focus REGEX] [--thread NAME] [--diff OTHER [--relative]] [--collapsed out.folded] [--json out.json]
```
Formats: pstats, V8 `.cpuprofile`, Chrome trace JSON, speedscope, folded stacks, timestamped
xtrace. Columns: self%, total%, time, `max×` (Amdahl ceiling), calls (pstats exact; xtrace
traced-command count). Chrome traces also print long tasks and main-thread event totals.

## scaling
```bash
perfkit scaling --cmd "python bench.py {n}" --sizes 1000,2000,4000,8000 [--runs 5] [--max-exponent 1.3] [--gate-on tail|fit]
perfkit scaling --csv sizes_times.csv
```
Reports per-size medians, the fitted log-log exponent with R², local exponents between adjacent
sizes, and the tail exponent (two largest sizes). `--max-exponent` exits 1 when exceeded.

## ledger
```bash
perfkit ledger add .perf/<c> --id E3 --hotspot "..." --hypothesis "... expect ~2x" --change "..."
                  --compare cmp.json [--bench REGEX] --guard "..." --decision kept|reverted|kept-simplification|abandoned|baseline
                  [--commit SHA] [--notes ...] [--strict]
perfkit ledger show .perf/<c>
```
`--quest-task <id>` also appends the record as a note on that Quest task. It needs the `quest` CLI and
`PERFKIT_ACTOR` / `PERFKIT_ACTOR_KIND` / `PERFKIT_ACCOUNTABLE_HUMAN`, or the `LORE_QUEST_*` equivalents. It exits 3
if the note can't be written. Appends to `.perf/<c>/experiments.jsonl`. Lints: kept without `improved` verdict, kept without a
guard, kept without a comparison. `--strict` exits 1 on lint.

## gate
```bash
perfkit gate --policy perf-policy.toml [--policy-ref <base sha>] [--test-policy test-policy.toml] --compare cmp.json
             [--compare more.json] [--metrics m.json ...] [--rigor R4] [--json out.json]
perfkit suite --policy perf-policy.toml [--policy-ref <base sha>] --base <base checkout> --head <head checkout> [--only REGEX] [--out-dir perf-ci]
```
Rigor is the max of `test-policy.toml`'s default and the tiers whose `paths` overlap a benchmark's `paths`, the
perf-policy tier, and `--rigor` (ADR-0004).
Checks each comparison against the tier tolerance (`[[tier]] benchmarks/paths` globs,
`max_regression`, `rigor`), the run-count floor, and blocks `inconclusive` at R4+; checks
`[[budget]]` metrics (`max`/`min`) against flat metric JSON files (`{"web": {"lcp_ms": 1800}}` →
`web.lcp_ms`). Exit 1 on any failure. See perf-ci for the policy format.
