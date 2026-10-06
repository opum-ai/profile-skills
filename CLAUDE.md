<!-- quest:agent-instructions:begin -->
# Quest agent instructions

This project uses Quest CLI 0.12.0 for tracker operations. Run `quest manifest --json` to discover the supported command contract.

Read the matching guide before tracker work: `quest instructions overview` for the command set and machine contract, `quest instructions task-creation` before creating or splitting tasks, `quest instructions task-execution` before claiming, planning, or recording progress, `quest instructions task-finalization` before checking acceptance criteria or closing a task, and `quest instructions workspace` for initialization, managed instructions, and Backlog.md migration. `quest instructions --list` lists every guide. Search for an existing record with `quest search "<query>" --json` before creating one, and run `quest help <command>` for a command's options and examples.

Quest writes require an explicit actor declaration: `--actor <id> --actor-kind human` for a person, or `--actor <id> --actor-kind delegated-agent --accountable-human <id>` for an agent acting on a person's behalf. Do not edit Quest-authored records directly. CI should run `quest agents --check --require-installed --target claude`: current instructions, and a version-only difference (only the pinned Quest CLI version number is stale) both exit 0; missing, drifted, or malformed managed instructions exit 6. Quest does not retry write conflicts automatically; callers should read the latest task state and perform their own bounded retry when a command returns conflict/exit 5.
<!-- quest:agent-instructions:end -->

<!-- lore:agents:begin -->
This repo uses **lore** — an OKF-native documentation CLI — for the docs bundle under `docs/`.
Drive docs work through `lore` (not a plain editor or `grep`) so Story <-> Task coupling, managed
blocks, and cross-links stay coherent.

- **Find and read docs:** `lore query "<words>" --limit 5`, then `lore read <id>` for the best hit.
- **Skill:** `.claude/skills/lore/SKILL.md` — how to drive lore.
- **Just-in-time detail:** run `lore instructions` for the canonical agent loop, then
  `lore instructions <topic>` (`retrieval`, `linking`, `sync`, `check`, `validation`, `types`, `workspace`, `agents`).
<!-- lore:agents:end -->

<!-- profile-skills:dev:begin -->
## Developing profile-skills

- **Skills:** `skills/perf-optimize`, `skills/perf-measure`, `skills/perf-ci`, symlinked into `.claude/skills/`. The
  engine `perfkit` lives in `skills/perf-measure/scripts/` and is stdlib-only Python 3.9+.
- **Engine tests:** `uv run --python 3.12 --with pytest python -m pytest -q tests` (also run with `--python 3.9`).
- **Graders:**
  - `python3 evals/grade.py <eval> <run-dir>`.
  - After changing a grader, re-prove it:
    `python3 evals/selftest/build_variants.py evals/.selftest && GRADER_FAST=1 python3 evals/selftest/prove_graders.py evals/.selftest`.
- **CI gate proof:** `evals/selftest/prove_ci_gate.sh evals/.selftest-ci`.
- **Clean up after yourself:**
  - `.perf/`, `evals/.selftest*/`, `evals/workspaces/` and `evals/.grader-cache/` are git-ignored scratch;
  - delete them when their results are recorded;
  - keep proofs in `evals/results/`.
- **Decisions** are ADR-0001…0007 in `docs/adr/`. Read them before changing behavior.
<!-- profile-skills:dev:end -->

<!-- profile-skills:perf-rules:begin -->
## Performance rules (perf-policy.toml, enforced by `perfkit gate`)

When a change is meant to make something faster or leaner, or touches a path in a perf tier:
1. **Measure before and after.** Use an interleaved A/B with ≥10 runs per arm
   (`perfkit abtest` / `compare`). Report the ratio with its 95% CI, not a single timing.
   Changes inside the noise floor are "no change".
2. **Profile before optimizing.** Name the hotspot and its share from a saved profile. Don't
   optimize code that the profile doesn't show as hot.
3. **Correctness first.** Tests must stay green and outputs identical. A faster wrong answer
   is a bug.
4. **Never touch the measuring stick to get green.** Don't edit benchmarks, workloads,
   fixtures, timing harnesses or `perf-policy.toml` in the same change as the code they
   judge. No caches keyed on benchmark inputs. No special-casing fixtures.
5. **Check memory and tails.** A speedup that regresses peak memory, p99 or bundle size is
   a trade-off to surface, not a silent win.
6. **Concurrency is a correctness change.** New parallelism, caching, batching or lock
   removal needs a race test or formal verification (proof-skills).
7. **Work at the effective rigor.** That is the highest of the project default, the tiers you
   touch, and any `Rigor:` trailer. At R4/R5, an inconclusive result is a failed gate, not a
   footnote.
<!-- profile-skills:perf-rules:end -->
