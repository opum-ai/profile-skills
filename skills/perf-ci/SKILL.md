---
name: perf-ci
description: Keep performance from regressing as agents ship changes - adopt perf-policy.toml (benchmarks, noise-calibrated tolerances, budgets for latency, startup, memory, bundle size, query/exec counts and Core Web Vitals) on top of test-skills' R1-R5 rigor tiers, and wire a CI gate that builds base and head on the same runner, compares them interleaved and paired with a confidence-interval rule (perfkit suite + gate), reads its policy from the base branch so a PR can't loosen it, and is proven to fail on an injected regression and pass a clean change; CodSpeed, Bencher, github-action-benchmark, Lighthouse CI and size-limit where they fit. Use this skill whenever the user asks to add performance or benchmark checks to CI, catch perf regressions in PRs, set performance budgets or SLOs, track benchmarks over time, fix flaky perf tests, gate bundle size or Lighthouse scores, or add performance rules for agents to a repo. For one-off measurement use perf-measure; for optimizing use perf-optimize.
---

# perf-ci

Performance regressions arrive one plausible PR at a time, and agents raise the rate. A
gate that works:
1. **Compares like with like.** Base and head are built and measured on the same runner, in
   one job, interleaved and analysed in pairs.
   - GitHub-hosted runners have about 2.7% CV, and CPU models differ behind one label.
   - Comparing against stored numbers from other runs produces flaky gates: a 2% threshold
     gives about 45% false positives there.
2. **Decides with ADR-0005's rule**, with tolerances set from measured A/A noise. No single
   runs, no absolute wall-time asserts on shared runners.
3. **Can't be loosened by the PR it judges.** The policy and the benchmark harness are read
   from the base revision.
4. **Is proven both ways** before you call it done.

`PK=${CLAUDE_SKILL_DIR}/../perf-measure/scripts/perfkit.py`. Templates are in `assets/`.

## Workflow

1. **Inventory first.** Collect:
   - existing benchmarks: pytest-benchmark, pyperf, asv, mitata, Vitest bench, hyperfine
     scripts;
   - CI jobs and runner types;
   - existing budgets: size-limit, LHCI, `assertNumQueries`;
   - `test-policy.toml` (rigor tiers, CI tiers);
   - which paths are hot.

   Reuse what's there.
2. **Pick a strategy per metric** (`references/strategies.md`):

   | Metric | PR gate |
   |---|---|
   | CPU-bound wall time (CLI, library hot path) | `perfkit suite`: same-runner interleaved paired A/B; tolerance ≥ max(5%, 2.5× A/A spread), typically 7–10% on GitHub-hosted runners |
   | many micro-benchmarks, tight thresholds | CodSpeed simulation (instruction counts, Linux; excludes I/O) |
   | deterministic counts: bytes, queries, execs, allocations | `[[metric]]` + `[[budget]]`, exact |
   | page load / interaction | `browser_trace.mjs` metrics or LHCI, median of 5, generous budgets |
   | trends on main | Bencher / github-action-benchmark / asv, plus change-point detection; not PR-blocking |

3. **Adopt the policy.** Copy `assets/perf-policy.toml` to the repo root.
   - **Rigor comes from `test-policy.toml` (ADR-0004).** Give each `[[benchmark]]` the
     `paths` it protects, so the gate looks up their tier. perf-policy tiers may only raise
     rigor. Without test-skills, the default is R3.
   - **Collect samples with the stack's tool (ADR-0006).** Benchmark commands can wrap
     pyperf, mitata or hyperfine (`--engine hyperfine`). perfkit's rule decides.
   - **Benchmarks:** fixed realistic inputs; each run prints a digest of its result, so the
     output-equivalence check means something; at least 0.1 s per run.
   - **Calibrate tolerances from A/A noise** on the runner class: run the suite with both
     arms at the same commit, 2–3 times. Set `min_effect` ≥ the largest A/A |change|, and
     `max_regression` ≥ 2× that. Record the A/A numbers as comments in the policy.
4. **Vendor perfkit** with `${CLAUDE_SKILL_DIR}/scripts/vendor_perfkit.sh tools/perfkit`
   (stdlib only), so CI doesn't depend on the plugin.
5. **Wire CI** from `assets/github-actions.yml`:
   - check out base and head; build both identically;
   - run `perfkit suite --policy-ref <base sha>`, then `perfkit gate --policy-ref <base sha>`;
   - upload artifacts and write a step summary.

   Also:
   - keep `shell: bash` (pipefail), or a failing gate behind `| tee` shows green;
   - run the **base revision's copy of the benchmark scripts**, so a PR can't weaken the
     benchmark judging it;
   - decide path filtering *inside* the job, so the check always reports and can be
     required;
   - protect `perf-policy.toml`, `benchmarks/` and `.github/workflows/` with CODEOWNERS. PR
     workflows run the PR's own copy of the workflow file, so only review can stop a PR from
     switching the gate off.
6. **Tiers.**
   - **PR:** the benchmarks whose `paths` the diff touches, within about 10 minutes.
   - **main:** the full suite, with history recorded.
   - **nightly:** R4 run counts, hold-out workloads, browser lab runs.

   Align with test-ci's tiers.
7. **Prove the gate both ways.** This is not optional. Show the output of each case:
   - head == base (a no-op or docstring change): **PASS**;
   - an injected regression (a `sleep`, a quadratic loop, or an uncompiled regex in the hot
     path): **FAIL** with `regressed`;
   - a PR that also loosens `perf-policy.toml` or shrinks the benchmark: still **FAIL**,
     judged by base's rules;
   - a regression below tolerance: PASS with a warning. Say the gate's detection floor out
     loud.

   Record the results in the PR description and a lore note.
8. **Agent rules.** Add `assets/agent-block.md` to `CLAUDE.md` / `AGENTS.md`.

## Flaky gates

- **Never retry-until-green.** Instead:
  - measure the benchmark's A/A spread;
  - lengthen its workload;
  - rely on the top-ups (`max_runs`) and pairing;
  - or move it to instruction counts or nightly.
- Quarantine a noisy benchmark with an owner and an expiry, as test-ci does for tests.
- Record the runner's CPU model with every result (`perfkit doctor`). A CPU change explains
  many "regressions" in history.

## Records and hand-offs

- **Quest:** a gate failure on main, or a budget breach, becomes a Quest task with the
  `gate.json` numbers attached. Calibration and the both-ways proof go in a lore note
  linked from the adoption task.
- **test-skills:** tier names and rigor live in `test-policy.toml`. Perf jobs follow test-ci's
  PR/main/nightly tiers and time budgets. Deterministic budgets that belong next to the code
  (query counts, memory limits) go through test-plan's admission rules.
- **proof-skills:** none directly. A gate measures; it doesn't prove. Concurrency changes
  flagged by perf-measure's review mode go to formal-verify.
- **housekeeping-skills:** CI artifacts are uploaded, not committed. Local `perf-ci/` and
  `.perf/` outputs are disposable (`.housekeeping.toml [junk] patterns`).

## Reference files

- `references/strategies.md`: same-runner A/B, instruction counts, Bencher, github-action-benchmark, asv, change points, choosing tolerances.
- `references/web-budgets.md`: LHCI, size-limit, lab-vitals budgets, field data.
- `references/policy.md`: the perf-policy.toml schema and how `suite` and `gate` decide.
- `assets/perf-policy.toml`, `assets/github-actions.yml`, `assets/lighthouserc.json`, `assets/agent-block.md`; `scripts/vendor_perfkit.sh`.
