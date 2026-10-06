---
name: perf-measure
description: Gather performance evidence without changing the code - profile to find where time or memory goes (Python, Node, Bun, browser, Bash), benchmark and compare two versions/branches/runtimes with interleaved runs and a confidence-interval verdict, verify someone's claimed speedup by independent re-measurement, or review a diff/PR for performance regressions with measured confirmation. Use this skill whenever the user asks to profile, find a bottleneck or hotspot, "why is this slow", "where is the time going", "what's using the memory", wants a flame graph, asks to benchmark or compare implementations, "is this faster", "did this regress", "is this speedup real", "will this PR be slow", "check this for perf issues", or hands you a .prof, .cpuprofile, speedscope, trace.json or benchmark JSON. To change code to make it faster use perf-optimize; to add CI gates use perf-ci.
---

# perf-measure

This skill answers performance questions with evidence, and does not edit the code under
study. It has four modes. Pick the one that matches the question:

| Mode | Question | Output |
|---|---|---|
| **profile** | Where does the time or memory go? | Hotspot table with shares and Amdahl ceilings, and why each is expensive |
| **bench** | Is B faster than A? By how much? Does it scale? | Verdict with ratio, 95% CI, n, environment |
| **verify** | Is this claimed speedup real? | Independent re-measurement and whether it reproduces the claim |
| **review** | Will this diff regress performance? | Findings ranked by severity, blockers confirmed by measurement |

The engine is `perfkit` (stdlib Python 3.9+): `PK=${CLAUDE_SKILL_DIR}/scripts/perfkit.py`.
The command reference is in `references/perfkit.md`.

## Rules that apply in every mode

- **One decision rule (ADR-0005).** "Faster" or "slower" is decided only by `perfkit compare`.
  - It needs interleaved runs in fresh processes, ≥10 per arm at R3. Rigor comes from
    `test-policy.toml` (ADR-0004): 20 per arm at R4, 30 at R5.
  - Verdicts are **improved** or **regressed** when the 95% CI on the median ratio excludes
    1.0, the point estimate is past the minimum effect (3% locally, 10% on shared CI, or the
    measured MDE if larger), and p < 0.05 (0.01 at R4+).
  - Interleaved samples are analysed as **paired blocks** (Wilcoxon signed-rank on per-block
    ratios), which cancels drift both arms share.
  - Anything else is `equivalent`, `below-threshold` or `inconclusive`. Report it as such;
    never round noise into a result.
- **Best-of-breed tools collect; perfkit decides (ADR-0006).** The tools are py-spy,
  Scalene, pyperf, memray, `node --cpu-prof`, mitata, @platformatic/flame and hyperfine.
  Install them on demand:
  - user-level first: `uv tool install py-spy`, `uv run --with scalene …`,
    `npm i -D mitata @platformatic/flame` in a scratch dir;
  - **ask before system-wide installs** (`brew install hyperfine`).

  Their own statistics are reported alongside, but they never decide.
- **Execute scripts; don't replay them.** In Claude Code's interactive zsh, `grep` and `find`
  are shell functions backed by bundled ugrep/bfs. Time shell code by running the script
  (`bash ./x.sh`), never by pasting its commands into your shell.
- **Artefacts go in `.perf/<concern>/`** (ADR-0007): profiles, traces, heap snapshots, flame
  graphs, raw JSON.
  - Make sure `.perf/` is git-ignored.
  - Heap snapshots contain program data and are never committed.
  - Cite small summaries (hotspot JSON, comparison JSON) in the report.
- Run `python3 $PK doctor` first. It lists installed tools, counter support, and noise
  warnings (load, battery, CI runner, bash version). Carry its warnings into the report.

## Mode: profile

1. **Name the question and reproduce the complaint.** Use the user's slow input, at a
   realistic size, through the real entry point, running ≥1–2 s or ≥2,000 samples. Profile
   the application, not the test runner, unless the suite itself is what's slow.
2. **Choose the profiler from the question:**

   | Runtime | CPU / wall (find hotspots) | Line level / memory | Notes |
   |---|---|---|---|
   | Python | **py-spy** `record -f speedscope` (`--idle` for wall, `--subprocesses`) | **Scalene** (`--cpu-only` 1.02× overhead; memory, copy volume); **memray** for allocations/leaks | macOS: py-spy needs root. If `sudo -n true` fails, ask the user to run the exact command with `! sudo …`; otherwise fall back to Scalene or pyinstrument and say so. cProfile for exact call counts. 3.15+: `python -m profiling.sampling` |
   | Node | `node --cpu-prof --cpu-prof-dir=.perf/<c>` | `--heap-prof`, heap snapshots + memlab | **@platformatic/flame** for flame graphs. File written only on normal exit |
   | Bun | `bun --cpu-prof-md` / `--cpu-prof` **for localisation only** | `--heap-prof-md` | Measured overhead 27–74%, and idle time is counted as JS self time (Bun #44077). Never take timings from a Bun profile; if the code also runs on Node, cross-check there |
   | Browser | `scripts/browser_trace.mjs` (Playwright, CPU/network throttle, `--interact`) | heap snapshots, memlab | Production build; median of ≥3 runs |
   | Bash / zsh | `scripts/xtrace.sh` (bash 5 `EPOCHREALTIME`; zsh native; bash 3.2 fallback flagged as inflated) | `/usr/bin/time -l` (macOS) / `time -v` | Count forks and execs: shell cost is usually process creation |
   | Native / any binary | `samply record --save-only` | Instruments, heaptrack | `references/native.md` |

   Flags and gotchas: `references/profile-python.md`, `profile-javascript.md` (Node and
   Bun), `profile-browser.md`, `profile-bash.md`, `memory.md`, `services.md` (HTTP, DB,
   N+1).
3. **Normalize:**
   `python3 $PK hotspots .perf/<c>/<profile> --project-root . --json .perf/<c>/hotspots.json`.
   This reads pstats, `.cpuprofile`, Chrome traces, speedscope, folded stacks and xtrace logs.
4. **Read it correctly:**
   - **Self** time is the cost inside a frame; **total** is the subsystem.
   - **`max×`** is the Amdahl ceiling: a 5% frame can never give more than ×1.05.
   - **Many calls to a cheap frame** means fix the caller.
   - **Tracing profilers** (cProfile, yappi, line_profiler) distort shares, by up to 80%
     reported vs 25% real in the Scalene paper. Take counts from them and shares from a
     sampler.
   - **A flame graph shows distribution, not efficiency.** A wide frame can be doing
     necessary work.
   - **A flat CPU profile of a slow program** means it is waiting: use wall mode, count
     queries, or look at event-loop delay.
5. **Report:**
   - the top frames (self, total, `max×`, calls), with `file:line` and *why* each is
     expensive;
   - the 1–3 highest-ceiling hypotheses for perf-optimize;
   - or "flat at this level; the cost is in X", with the evidence.

## Mode: bench

1. **Define the claim before measuring:**
   - the metric: wall, CPU, p99, RSS, startup, instructions;
   - the workload, and the arms A and B;
   - the minimum effect that matters.
2. **Collect samples with the right harness:**

   | Thing measured | Harness → perfkit |
   |---|---|
   | command, script, CLI, build (≥10 ms) | `perfkit abtest` (interleaved, output-checked, instruction counts recorded), or `--engine hyperfine` for hyperfine bursts per block |
   | Python function/snippet | **pyperf** (`-o a.json` / `-o b.json`, or `pyperf command`) → `perfkit compare a.json b.json` |
   | JS/TS function (Node, Bun) | **mitata** `run({ format: 'json' })` → `perfkit compare`; or a per-arm driver process under `abtest` for decisions |
   | HTTP service | k6 open-loop (constant-arrival-rate) / oha; alternate A/B runs (`references/bench-cli-and-load.md`) |
   | page | `browser_trace.mjs` medians, A/B alternated |
   | scaling | `perfkit scaling --cmd '… {n}' --sizes …` (tail exponent; ≥8× size span) |

   Two versions of the same repo: put each in a git worktree under `.perf/wt-*`, build both,
   then measure the built artefacts.
3. **Prove both arms did the same work.** Use `--require-same-output`, or assert inside the
   benchmark. Consume results so JIT and optimizers can't delete the work.
4. **Decide:** run `perfkit compare` (`references/stats.md`). Before reporting, go through
   the benchmarking-crimes checklist (`references/crimes.md`).
5. **Report** one line a reader can trust, then the details. For example: "B is 1.8× faster
   (ratio 0.55, 95% CI 0.53–0.57, paired n=20 interleaved, outputs identical, M4 on AC,
   load 3.1)".

## Mode: verify (someone claims a speedup)

The claim is a hypothesis, not a fact. Agents' speedups often don't reproduce: many published
agent speedups failed on other machines, and in one field study only 45.7% of agent
performance PRs included any validation at all.
1. Extract the claim: the metric, the workload, before and after, and the claimed ratio or
   CI.
2. Rebuild **both** versions yourself, from the base commit and the claimed commit, and run
   the same workload interleaved. Use the workload from the claim; if it's unstated, use a
   realistic one, plus a hold-out input it wasn't tuned on.
3. Check for gaming:
   - changes to benchmark, harness or fixture files in the diff;
   - caches keyed on benchmark inputs, or state persisting across runs;
   - work moved out of the timed region;
   - fixture-specific fast paths;
   - smaller workloads.
4. Verdict:
   - **reproduced:** your CI overlaps the claimed ratio, or lies within ±30% of it when no
     CI was given;
   - **partially reproduced:** real, but smaller;
   - **not reproduced:** report the measured numbers.

## Mode: review (a diff or PR)

1. Get `git diff <base>...<head>` and the PR text. Note every performance claim; each one
   gets verify mode.
2. For each changed function, establish **execution frequency × size**: per request, per row
   or per keystroke vs once at startup, and the realistic n. No blocker or major finding
   without this argument.
3. Scan with the catalogs: `references/antipatterns-python.md`, `-js.md`, `-browser.md`,
   `-bash.md`, `-data.md` (N+1, I/O, caching). `ruff check --select PERF,…` hints are hints
   only.
4. **Confirm blockers and majors by measurement:**
   - base vs head A/B on generated realistic input;
   - scaling exponents;
   - query or exec counts.

   Unmeasurable findings are labelled **suspected**.
5. Check the measuring stick. Is the PR editing benchmarks, fixtures, thresholds or
   `perf-policy.toml` alongside the code they judge? Are new caches bounded and safe? Are
   concurrency changes covered (see hand-offs)?
6. Write it up with `references/review-template.md`: verdict, findings with evidence, claims
   table, "checked and fine". Behaviour changes found along the way are correctness
   findings, and they outrank performance.

## Records and hand-offs

- **Quest:** in a Quest workspace, every review blocker or major, and every profile finding
  the user wants acted on, becomes a Quest task. The measurement goes in the description:
  ratio, CI, n, environment, evidence path. Use
  `quest task create … --actor … --actor-kind delegated-agent --accountable-human …`.
- **lore:** baselines that later work will compare against go into a lore Reference
  (`Perf report: <concern>`), linked from the task with `quest task edit <id> --doc …`.
- **test-skills:** a performance assertion worth keeping (a query-count budget, a scaling
  exponent bound, a memory limit) enters the suite only through test-plan's admission rules,
  or becomes a perf-ci budget instead.
- **proof-skills:** if a reviewed change alters a concurrency structure (threads, async
  fan-out, lock removal, batching atomicity, shared caches) or swaps an algorithm whose
  equivalence must hold for all inputs, flag it for formal-verify. Tests alone are not
  enough at R3+.
- **housekeeping-skills:** `.perf/` is disposable once summaries are recorded. Repos using
  housekeeping add `".perf"` to `.housekeeping.toml [junk] patterns`, so `tidy` trashes it
  when the task is done.

## Reference files

- `references/perfkit.md`: every perfkit command, input formats, output JSON.
- `references/stats.md`: the decision rule, pairing, noise, MDE and runs needed, multiple comparisons.
- `references/crimes.md`: benchmarking-crimes checklist.
- `references/profile-python.md`, `profile-javascript.md`, `profile-browser.md`, `profile-bash.md`, `memory.md`, `services.md`, `native.md`.
- `references/bench-python.md`, `bench-javascript.md`, `bench-cli-and-load.md`.
- `references/antipatterns-*.md`, `references/review-template.md`.
- `scripts/perfkit.py`, `scripts/browser_trace.mjs`, `scripts/xtrace.sh`.
