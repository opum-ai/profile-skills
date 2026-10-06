---
# yaml-language-server: $schema=../../.lore/schemas/reference.schema.json
type: Reference
title: "Release report: profile-skills v0.1.0"
tags:
  - release
  - report
summary: "Final report for the release-quality review: decisions, the three skills, integration, proofs, round-one results and open limitations."
generated:
  by: lore/0.12.0
  at: 2026-10-06T03:35:21.108Z
---

# Release report: profile-skills v0.1.0

Date: 2026-10-06. Tracks the owner's release brief (Phases 0–4). Quest: PSKI-1…PSKI-15. No commits have been made;
committing waits for the owner's approval.

## Decisions (all put to the owner)

| ADR | Decision | Owner's choice |
|---|---|---|
| [0001](../adr/0001-five-skills-split-by-activity-with-an-orchestrator.md) | Three skills: perf-optimize, perf-measure, perf-ci | A (three) |
| [0004](../adr/0004-share-rigor-profiles-with-test-skills.md) | Rigor from test-skills' `test-policy.toml`; perf-policy only raises it | A |
| [0005](../adr/0005-statistical-method-and-default-significance-rule.md) | Wall-clock primary; keep a change only if the 95% CI excludes 1, the effect exceeds the minimum, and p < 0.05 (0.01 at R4+); paired analysis of interleaved runs; instruction counts corroborate | A |
| [0006](../adr/0006-default-profiler-and-harness-per-stack.md) | Best-of-breed tools installed on demand; **the tools collect, perfkit decides** | B, plus the follow-up reconciliation |
| [0002](../adr/0002-stdlib-perfkit-engine-with-one-normalized-hotspot-format.md), [0003](../adr/0003-same-runner-interleaved-a-b-as-the-default-ci-gate.md), [0007](../adr/0007-artefacts-records-and-hand-offs.md) | Engine, CI gate, artefacts/records/hand-offs | Agent-decided under the brief; proposed for review |

## Research

- [State-of-the-art summary](state-of-the-art-in-performance-profiling-and-agent-driven-optimization.md)
- Research notes:
  - [Python](research-notes-python-profiling-and-benchmarking.md)
  - [JS/TS and browser](research-notes-javascript-typescript-and-browser-performance.md)
  - [methodology, statistics, Bash and CI](research-notes-methodology-statistics-bash-and-ci.md)
  - [tool matrix and methodology numbers](research-notes-tool-comparison-matrix-and-methodology-numbers.md), including
    measurements on this machine
  - [prior art and failure modes](research-notes-prior-art-in-agent-performance-skills-and-failure-modes.md)
- [Audit of the drafted skills](audit-of-the-drafted-profile-skills-pre-release-review.md)

## The skills

- **perf-optimize:**
  - the loop, with explicit rules: baseline → profile → one hypothesis → one change → re-measure;
  - keep only if significant AND green; otherwise revert and record;
  - stop at the target, below the MDE, or at the cap;
  - never trade correctness or readability for an unmeasured gain;
  - pins behaviour first (coverage; tmx kill matrix at R4+).
- **perf-measure:** profile / bench / verify / review, with perfkit, `browser_trace.mjs` and `xtrace.sh` (bash 5,
  zsh, and a bash 3.2 fallback).
- **perf-ci:** perf-policy.toml on the R1–R5 tiers, and a same-runner interleaved paired gate with the policy read from
  base.
- **Hand-offs (each skill names them):**
  - test-skills: pinning, admission, tiers;
  - proof-skills: concurrency structure, and algorithm equivalence for all inputs;
  - housekeeping-skills: `.perf/` cleanup through `[junk] patterns`.

## Integration on a real example

perf-optimize was run on this repository's own `perfkit hotspots` (Quest PSKI-15):
- **Result:** ×2.34 faster and 4.9× less memory on a 134 MB trace; ×1.43 on a 527 MB hold-out.
- **Experiments:** 5, with 1 rejected and its numbers recorded.
- **Bug found:** the equivalence harness surfaced a real determinism bug, fixed first.
- **Records:** every experiment is a Quest note; the [lore report](perf-report-perfkit-hotspots-on-large-chrome-traces.md)
  is linked from the task.

## Proofs

- **Engine:** 43 tests, passing on Python 3.12 (Python 3.9 skips the two that need `tomllib`).
- **Graders, proven both ways:**
  - 19 known-good and known-bad answers give 171/171 predicted cells;
  - 18/18 mutations behave as predicted;
  - `evals/results/round1-proofs/graders-proof.json`.
- **perf-ci gate, proven both ways:**
  - a clean change passes;
  - an injected regression fails;
  - a PR that also loosens its own policy still fails;
  - a 2% slowdown passes (the stated detection floor);
  - `evals/results/round1-proofs/ci-gate-proof.json`.

## Round-one evaluation

Details and the full table: [Skill evaluation suite](../stories/skill-evaluation-suite.md).
- **Outcomes:** 18/18 for both arms. No outcome difference; the baseline was equal or slightly faster against the
  expert.
- **Process:** 8/9 with skills vs 2/9 without.
- **Cost:** 1.3–2.9× the tokens and 2.6–8.5× the wall time.
- **Honest reading:** for Opus 5.5 on these fixtures, the skills buy verifiable evidence and claim honesty, not better
  code, and they cost too much for that today.

The first round-one attempt (fixtures v1) was withdrawn after the owner pointed out that its score gap came only
from saved evidence. Scoring was redesigned outcome-first.

## Open limitations

1. **Cost** (highest priority for the next iteration): sequential stopping when effects dwarf noise, no verifier
   below R4, a lighter ledger for obvious wins.
2. **No outcome discrimination yet:** this needs weaker models, larger codebases where localisation is hard, or
   several runs per arm.
3. **Trigger descriptions** have not been optimized with the description loop (PSKI-9).
4. **Not exercised here:** CodSpeed simulation, Linux `perf`, and the GitHub-hosted runner path. The CI gate was
   proven locally only.
5. **macOS limits:**
   - py-spy needs root (the skill asks the user or falls back);
   - Bun's profiler has 27–74% overhead and an idle-time attribution bug;
   - `/usr/bin/time -l` instruction counts cover the direct child only.
6. **Expert references are not ceilings:** the Bash baseline preserved more of the original's quirks than the expert
   solution did.
