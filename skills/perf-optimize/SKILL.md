---
name: perf-optimize
description: Make code measurably faster or leaner without breaking it - the recursive loop of baseline → profile → one hypothesis → one change → re-measure with statistics → keep only if significant AND tests stay green, otherwise revert and record why, repeat until a stop rule fires - for Python, JavaScript/TypeScript on Node and Bun, browser pages and Bash. Pins behaviour first (tests and coverage of the changed path, kill matrix at higher rigor), records every experiment (kept or rejected) in Quest and lore, hands concurrency and algorithm-equivalence questions to proof-skills, and scales evidence with the R1-R5 rigor profiles. Use this skill whenever the user asks to speed something up, optimize, reduce latency/memory/startup/build time/bundle size/page load, says something is "slow", "takes forever", "times out" or "uses too much memory", wants a performance pass, or asks to iteratively/recursively improve performance - even if they never say "profile". For measuring or reviewing without changing code use perf-measure; for CI gates use perf-ci.
---

# perf-optimize

Agents fail at performance work in specific, well-measured ways:
- On SWE-fficiency they reach under a quarter of expert speedups. 68% of the expert gains
  sit in functions the agent never touched, 15–45% of the agents' patches break tests, and
  they stop after the first small win.
- They mistake noise for wins and quietly game benchmarks (GSO had to add a hack detector).
- In the field, only 45.7% of agent performance PRs include any validation.

What works is a **profiler in the loop**: PerfAgent doubled expert-matching rates with it.
That needs a trustworthy evaluator and correctness as a hard gate. This skill is that loop,
with explicit rules.

Measurement, profiling and the decision rule come from perf-measure:
`PK=${CLAUDE_SKILL_DIR}/../perf-measure/scripts/perfkit.py`. Read perf-measure's SKILL.md
"Rules that apply in every mode" once before starting.

## Step 0: Rigor, records, environment

- **Rigor (ADR-0004).** Effective rigor = max(`test-policy.toml` default and the tier of every
  path you will touch, `perf-policy.toml` tiers, anything the user declared). Raise it for
  money, auth, data integrity or shared hot paths; never lower it. State it in your first
  message. What each level demands: `references/rigor.md`.
- **Records (ADR-0007).** In a Quest workspace, find or create the task for this campaign
  (`quest search`, then `quest task create`), and put the scope in its description.
  Artefacts go in `.perf/<concern>/`, which must be git-ignored. Each experiment is appended
  to the task with `perfkit ledger add --quest-task <id>`. The final report becomes a lore
  Reference. Details: `references/records.md`.
- **Environment.** Run `python3 $PK doctor`. Fix what you can (AC power, close heavy apps,
  install the tool you need per ADR-0006), and carry the remaining warnings into the report.

## The loop and its rules

1. **Scope.** Before touching code, write in `.perf/<concern>/SCOPE.md` and the task:
   - **one primary metric**, and the secondary metrics that must not regress (memory, p99,
     bundle size, CLS);
   - **the workload**, at the user's slow case and size, with its input checksum;
   - **a hold-out workload** you will not tune on: another seed, a 2–4× size, or a real
     sample;
   - **the target**, an **iteration cap** (default 10 experiments) and a time budget.
2. **Pin behaviour first.** A speedup that changes behaviour is a bug.
   - Run the tests and record the counts.
   - Measure **coverage of the code you intend to change**: `coverage run -m pytest` /
     `c8` / `bun test --coverage`, then `coverage report --include=<files>`.
   - Below about 90% line coverage of those lines, add pinning tests first. Use test-plan's
     rules (tables/properties, prune scaffolding), or keep an **equivalence harness** in
     `.perf/<concern>/` that diffs old vs new outputs on the workload plus randomized and
     edge inputs.
   - At **R4+**, also take test-skills' mutation kill matrix on the changed code
     (`tmx collect-pytest`, or a Stryker import for JS) before the change. Its kills must
     survive afterwards.
   - List the semantics to preserve: order, floats, errors, laziness, input mutation, side
     effects, concurrency (`references/guards.md`).
3. **Baseline.** Interleaved A/B of the current code against itself (`perfkit abtest`, ≥10
   runs per arm at R3). This measures noise and gives the **minimum detectable effect** for
   the session. Record median, IQR, MDE and environment.
4. **Profile** the same workload with perf-measure's profile mode, and save the hotspot
   table.
5. **One hypothesis.** Name the frame, its share, its Amdahl ceiling, the mechanism and a
   **predicted gain**. Walk the ladder top-down (`references/ladder.md`):
   do less work → algorithm/data structure → batch I/O → concurrency → caching →
   runtime/native → micro-tuning. Skip any hypothesis whose ceiling is below the MDE.
6. **One change.** Change exactly one thing, then run the tests and the equivalence harness.
   A failure is a revert.
7. **Re-measure** the candidate against the **incumbent** (the last kept state, in a worktree
   at `.perf/wt-incumbent`), interleaved and paired, with `--require-same-output`. Then run
   `perfkit compare`. This is ADR-0005's rule; nothing else decides.
8. **Keep or revert:**

   | Outcome | Action |
   |---|---|
   | verdict `improved` **and** tests and harness green **and** no secondary metric regressed beyond its tolerance | **keep**: commit `perf(<concern>): E<n> …`, advance the incumbent |
   | verdict `equivalent`/`below-threshold` and the code is clearly simpler | keep as `kept-simplification`, and say what got simpler |
   | anything else | **revert** (`git checkout -- <files>` / `git stash drop`) and record why, with the numbers |

   Every outcome is logged:
   `python3 $PK ledger add .perf/<c> --id E<n> --hotspot … --hypothesis "… expect ~2×" --change … --compare <cmp.json> --guard "<tests + harness result>" --decision kept|reverted --quest-task <id>`.
   Rejected experiments are evidence, so the next person doesn't retry them blind.
   If the measured gain is far below the prediction, your model of the program is wrong.
   Re-profile instead of stacking guesses.
9. **Re-profile and repeat** from step 4. The bottleneck moves after every win.
10. **Stop** when any of these holds, and name which one in the report:
    1. the target is met (confirmed on the hold-out workload too);
    2. the best remaining Amdahl ceiling, or the last gains, fall **below the MDE**;
    3. the **iteration cap** or budget is hit;
    4. three consecutive experiments were not kept;
    5. the next step needs a decision only the user can make: API or behaviour change, a new
       dependency, native code, infrastructure, or a trade-off on a gated metric.
11. **Confirm and report:**
    - Final interleaved A/B of the incumbent vs the original on the main **and hold-out**
      workloads, plus the full test suite.
    - Write the lore report (`references/report.md`): baseline, experiments kept *and
      rejected* with numbers, remaining hotspots with ceilings, caveats.
    - Link it from the Quest task, and summarize it in your final message.

## Rules that keep it honest

- **Never trade correctness or readability for an unmeasured gain.** A change that makes the
  code harder to read needs a measured, significant gain on a hot path. Otherwise revert it,
  even if it might be faster.
- **No profile, no change.** Every hypothesis cites a frame and share from a saved profile.
- **Never touch the measuring stick:** no edits to benchmarks, workloads, fixtures, timing
  harnesses, the guard, or the policy. Check `git diff --stat` before every claim. Fix a
  broken harness as its own logged step, then re-baseline.
- **No gaming:**
  - no caches keyed on benchmark inputs that production wouldn't hit;
  - no state persisting across runs;
  - no work moved outside the timed region;
  - no fixture-specific fast paths;
  - no smaller inputs.

  The hold-out workload exists to catch these.
- **One change per experiment,** measured against the incumbent. Bundled changes hide
  regressions.
- **Memory and tails count.** Agents almost never optimize memory, and often regress it.
  Peak RSS is recorded on every A/B (`--all-metrics`).

## Hand-offs

- **test-skills:**
  - pinning tests and characterisation tests go through test-plan; budgets follow test-ci
    and test-policy;
  - the kill matrix comes from test-audit's `tmx` at R4+;
  - never delete or weaken a test to get green.
- **proof-skills:** stop and hand the invariant to formal-verify (or lean-model /
  tlaplus-model) instead of trusting the tests:
  - when a change alters a **concurrency structure**: threads, async fan-out, removing or
    narrowing a lock, batching that changes atomicity, or a cache shared across requests;
  - when a change **replaces an algorithm** whose equivalence must hold for all inputs:
    incremental vs recompute, a custom index, a reordered reduction. Required at R4+, and
    recommended at R3 when the input space is large and structured.
  - Use proof-simplify to prove a lock or guard redundant before deleting it for speed.
- **housekeeping-skills:** when the campaign is done and recorded, `.perf/<concern>` and
  `.perf/wt-*` worktrees are disposable (`git worktree remove`; `tidy` trashes `.perf` when
  the repo lists it under `[junk] patterns`).
- **perf-measure / perf-ci:** use perf-measure's verify mode for an independent check of the
  final claim at R4. That is a read-only judge in a separate context, ideally a subagent. To
  lock in a win, add a perf-ci benchmark or budget.

## Recursive improvement

Each pass works on the output of the last. When one hotspot resists, use **candidate
fan-out** (`references/loop.md`): 2–4 genuinely different approaches, each in its own
worktree or subagent, all through the same guard and one multi-arm interleaved A/B. Keep the
best that passes and log the rest. The evaluator matters more than the search, so fan out
only once steps 2–3 are solid.

## Reference files

- `references/loop.md`: worktrees, function-level drivers, the ledger, stop rules, fan-out, handoff notes.
- `references/guards.md`: pinning and equivalence harnesses (Python, JS, Bash), the semantics checklist, anti-gaming checks, hold-outs.
- `references/ladder.md`: the optimization ladder per language.
- `references/rigor.md`: what R1–R5 require at each step.
- `references/records.md`: `.perf/` layout and cleanup, Quest notes, the lore report, a worked example.
- `references/report.md`: lore report and PR description templates.
