# profile-skills

**Measured performance engineering for agentic development.** Three Claude Code skills, and a small
stdlib engine, that make an agent's performance work trustworthy:
- they **profile before changing anything**, so effort goes to the measured hotspot;
- they decide "faster or not" with **one statistical rule**: interleaved, paired runs and a 95% CI on the ratio;
- they **keep a change only if it is significant and the tests stay green**, and record every rejected attempt with
  its numbers;
- they **gate regressions in CI** on the same runner, with a policy the PR can't loosen.

**Status:** v0.1.0. Owned by [Opum AI](https://github.com/opum-ai), MIT licensed. A companion to
[proof-skills](https://github.com/opum-ai/proof-skills) and [test-skills](https://github.com/opum-ai/test-skills).
Native support for [quest](https://github.com/opum-ai/quest-cli) (tasks) and
[lore](https://github.com/opum-ai/lore-cli) (docs).

## Why

Agents are measurably bad at performance work, in specific ways:
- **They optimize the wrong code.** On SWE-fficiency, agents reach under a quarter of expert speedups, and 68% of the
  expert gains sit in functions the agent never touched.
- **They break things.** 15–45% of agent patches break tests.
- **They stop early,** after the first small win.
- **They mistake noise for wins.** Many published agent speedups don't survive a change of machine, and under
  rigorous measurement only about 6% of LLM "performant" solutions were significantly faster.
- **They game benchmarks.** GSO had to add a hack detector after agents cached benchmark inputs.
- **They ship unvalidated claims.** Only 45.7% of agent performance PRs include any validation.

What works is a **profiler in the loop** with a trustworthy evaluator: PerfAgent doubled expert-matching rates that
way. These skills are that loop with explicit rules. The research and every source are in
[`docs/reference/`](docs/reference/state-of-the-art-in-performance-profiling-and-agent-driven-optimization.md).

## The skills

| Skill | Role |
|---|---|
| **`perf-optimize`** | "Make it faster." Runs the recursive loop: scope → pin behaviour (tests, coverage of the changed path, kill matrix at R4+) → baseline → profile → **one** hypothesis → **one** change → re-measure → keep only if significant **and** green, otherwise revert and record why. Stops on a target, the minimum detectable effect, or an iteration cap. |
| **`perf-measure`** | Evidence without code changes, in four modes. **profile**: where does time or memory go (Python, Node, Bun, browser, Bash). **bench**: is B faster. **verify**: is this claimed speedup real. **review**: will this diff regress. |
| **`perf-ci`** | `perf-policy.toml` budgets and tolerances on the R1–R5 tiers from `test-policy.toml`, plus a same-runner, interleaved, paired base-vs-head gate that reads its policy from the base branch. It is proven to fail on an injected regression and to pass a clean change. |

### Decisions (ADRs in [`docs/adr/`](docs/adr/))

| ADR | Decision |
|---|---|
| 0001 | Three skills by activity (owner's choice over five) |
| 0002 | One stdlib engine, perfkit, with one normalized hotspot format |
| 0003 | Same-runner interleaved A/B as the default CI gate |
| 0004 | Rigor from test-skills' `test-policy.toml` (R1–R5). perf-policy may only raise it |
| 0005 | **The rule:** wall-clock primary. Keep a change only if the 95% CI on the median ratio excludes 1, the effect exceeds the minimum (3% local, 10% shared CI), and p < 0.05 (0.01 at R4+). Interleaved runs are analysed as paired blocks. Instruction counts corroborate but never decide |
| 0006 | Best-of-breed tools, installed on demand: py-spy, Scalene, memray, pyperf; `node --cpu-prof`, mitata, @platformatic/flame; Bun's own profiler for localisation only; hyperfine. **The tools collect, perfkit decides** |
| 0007 | Artefacts in git-ignored `.perf/` with a housekeeping cleanup rule; findings and experiments in Quest; reports in lore; hand-offs to test-skills, proof-skills and housekeeping-skills |

## The engine: `perfkit`

`skills/perf-measure/scripts/perfkit.py`: stdlib-only Python 3.9+, vendorable with
`skills/perf-ci/scripts/vendor_perfkit.sh`.

```text
doctor     tools installed, instruction-counter support, noise warnings (load, battery, CI, bash version)
abtest     interleaved A/B in fresh processes; stdout equivalence; peak RSS; instructions retired; --engine hyperfine
compare    paired (Wilcoxon on per-block ratios) or unpaired (Mann-Whitney) + bootstrap CI + verdict at a min effect;
           reads perfkit, pyperf, hyperfine, pytest-benchmark and mitata JSON
hotspots   one table from pstats, .cpuprofile (Node/Bun/Deno), Chrome traces, speedscope, folded stacks, bash/zsh xtrace;
           self/total/Amdahl ceiling; --project-root folds library frames; --diff
scaling    time vs input size; log-log tail exponent (empirical big-O); --max-exponent as a test
ledger     experiment log; --quest-task appends each kept OR rejected experiment to a Quest task with its numbers
suite/gate perf-policy.toml in CI: interleaved base-vs-head, top-up runs while inconclusive, budgets, policy from base
```

Helpers:
- `browser_trace.mjs`: Playwright traces with CPU and network throttling, and lab vitals including an INP proxy.
- `xtrace.sh`: per-line timing for bash 5 and zsh, with a flagged fallback for macOS bash 3.2.

## Install

```text
/plugin marketplace add opum-ai/opum-marketplace
/plugin install profile-skills@opum
```

The skills install tools on demand at user level (`uv tool install py-spy`, `uv run --with scalene`,
`npm i -D mitata`). They ask before system-wide installs (`brew install hyperfine bash`). On macOS, py-spy needs
`sudo`; the skill asks you to run that one command with `! sudo …`, or falls back to Scalene.

## Usage

```text
> The nightly report job takes forever now that we have 250k rows. Make it fast; output must not change.
> Where is the time going in `node src/cli.ts fixtures/big.json`? It runs on Node and Bun.
> Is this PR's "2x faster" claim real?
> Review feature/order-summary for performance problems before we merge.
> Add a perf regression gate to CI for fastparse.parse.
```

## Evaluation

Graders never trust the agent:
- hidden inputs (other seeds and sizes) are diffed byte for byte against the pristine code;
- the fixture's own tests are re-run against the candidate;
- speed is re-measured independently, cold, with a fresh HOME and tree per run, so on-disk caches can't help;
- the agent's claimed speedup must reproduce within ±50% of the grader's CI;
- a profiler artefact and A/B evidence (≥5 runs per arm) must exist.

**The graders are proven both ways** ([`evals/selftest/`](evals/selftest/)):
- 12 known-good and known-bad answers produce exactly the predicted pass/fail matrix (84/84 cells). The bad answers
  cover wrong semantics, unmeasured claims, path-gaming, cross-run caching and weakened tests.
- Forcing each assertion to constant True or False flips exactly the predicted cells (14/14 mutations).
- **The perf-ci gate is proven both ways:** a clean change passes; injected regressions fail; a PR that also
  loosens its own policy still fails; a ~2% slowdown below the threshold passes, which shows the detection floor
  ([`evals/results/round1-proofs/`](evals/results/round1-proofs/)).

**Round one** used 3 fixtures (Python, TypeScript on Node and Bun, Bash), with and without the skills, on
`claude-opus-5-5`, one run per arm. It was scored **outcome-first**, so the score reflects the code an agent left
behind, not whether it followed the skill's procedure. The fixtures were built so outcomes could differ:
- a decoy hotspot;
- an eager debug log that dominates after the obvious fix;
- a 256 MB memory limit at 2× volume;
- a documented 16-request registry limit;
- a locale trap.

| | Outcome assertions (18) | Process assertions (9) | Speed vs expert at 2× volume | Tokens | Wall time |
|---|---|---|---|---|---|
| With skills | **18/18** | 8/9 | 1.22 / 1.00 / 1.44 | 1.3–2.9× | 2.6–8.5× |
| Without | **18/18** | 2/9 | 1.37 / 1.01 / 1.74 | 1× | 1× |

- **No outcome difference.** On these tasks, Opus 5.5 without the skills produced equally correct code that was as
  fast or slightly faster, at a fraction of the cost.
- **What the skills add is evidence.** Every with-skill reply carried a saved profile, A/B data and a headline claim
  that reproduced on the grader's independent re-run. One run's independent verifier caught an inflated number
  (553 s claimed vs 179 s re-measured).

This is reported as measured; see [Skill evaluation suite](docs/stories/skill-evaluation-suite.md) for the full table,
the withdrawn first attempt, and what it implies for cost and positioning. Wave 1 (the draft five skills) is recorded
there too.

**A real campaign on this repository:** perf-optimize sped up `perfkit hotspots` on large browser traces ×2.34, and
cut peak RSS from 785 MB to 162 MB, with identical output. That is 5 experiments, 1 rejected with its numbers, all
recorded on Quest task PSKI-15 and in a [lore report](docs/reference/perf-report-perfkit-hotspots-on-large-chrome-traces.md).

## Repository layout

```
.claude-plugin/plugin.json     plugin manifest (the repo root is the plugin root)
skills/perf-optimize/          the loop: SKILL.md + references (loop, guards, ladder, rigor, records, report)
skills/perf-measure/           profile/bench/verify/review + scripts/ (perfkit, browser_trace.mjs, xtrace.sh)
skills/perf-ci/                policy, CI templates, vendor script
tests/                         perfkit's own suite (Python 3.9 and 3.12)
evals/                         fixtures, objective graders, grader self-tests, results
docs/                          OKF bundle: epic, stories, ADRs, research references, perf reports
```

## Development

```bash
uv run --python 3.12 --with pytest python -m pytest -q tests      # engine (also --python 3.9)
python3 evals/selftest/build_variants.py evals/.selftest && GRADER_FAST=1 python3 evals/selftest/prove_graders.py evals/.selftest
evals/selftest/prove_ci_gate.sh evals/.selftest-ci
claude plugin validate . && lore check && quest agents --check --require-installed --target claude
```

Track work with `quest`, and write docs with `lore` (see `CLAUDE.md`).

## Known limitations

Tracked in Quest:
- **Trigger descriptions are not yet optimized** with the skill-creator description loop (PSKI-9).
- **Round one is small:** 3 fixtures, one run per arm. It showed no outcome advantage over a strong baseline, and the
  skills cost 1.3–2.9× the tokens. Cost reduction is the next iteration.
- **macOS-specific limits:**
  - py-spy needs root;
  - Bun's profiler costs 27–74% and counts idle time as JS self time (Bun #44077);
  - instruction counts via `/usr/bin/time -l` cover only the direct child process.
- **CodSpeed simulation and Linux `perf` paths** are documented but were not exercised on this machine.

## License

MIT. See [LICENSE](LICENSE).
