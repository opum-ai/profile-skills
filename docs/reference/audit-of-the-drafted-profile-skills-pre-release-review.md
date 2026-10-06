---
# yaml-language-server: $schema=../../.lore/schemas/reference.schema.json
type: Reference
title: Audit of the drafted profile-skills (pre-release review)
tags:
  - audit
  - skills
summary: Per drafted skill, what it claims, what evidence backs it today, and what the release-quality review changes.
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:06:26.888Z
---

# Audit of the drafted profile-skills (pre-release review)

Date: 2026-10-05. Scope: the five skills drafted in the first pass (`skills/perf-*`), the perfkit engine, and the
first eval wave. Tracked as PSKI-10. "Evidence today" lists only what has actually been run, not what the skill
text asserts.

## Summary

The drafts are grounded in a cited research pass ([summary](state-of-the-art-in-performance-profiling-and-agent-driven-optimization.md)
and three research-notes references). The engine is tested. The skills themselves are unproven against a baseline:
the only completed with/without comparison (PR review) showed little difference.
- Decisions were taken without the owner. ADRs 0001–0004 are reset to Proposed.
- Integration with test-skills (pinned behaviour before an optimisation), proof-skills (when to hand off an
  invariant), housekeeping-skills (where artefacts live) and Quest/lore (findings as tasks, reports as docs) is
  described loosely or not at all.

## Per skill

| Skill | What it claims | Evidence today | What this review changes |
|---|---|---|---|
| perf-optimize | A recursive loop (scope → guard → baseline → profile → hypothesis → one change → guard → interleaved A/B → keep/revert + ledger → re-profile) beats ad-hoc optimisation; anti-gaming via hold-out workloads; stop rules | None yet. The Python-optimisation eval was still running at audit time | Make loop rules explicit and checkable (significance AND green tests to keep; revert + record otherwise; stop rules incl. iteration cap). Require pinned behaviour (coverage of the changed path, ideally a tmx kill matrix) *before* the change. Name proof-skills hand-off triggers. Records go to Quest/lore, raw artefacts to `.perf/` with a cleanup rule |
| perf-profile | Picks the right profiler per question/runtime; one normalized hotspot table from six formats; browser trace + xtrace helpers | perfkit hotspots tested on pstats, cpuprofile (Node, Bun), Chrome trace (Playwright, real page), speedscope, collapsed, bash 3.2 and zsh xtrace. browser_trace.mjs measured a real page | Bun coverage from measurement on this machine (Bun 1.3.14: `--cpu-prof`, `--cpu-prof-md`, `--heap-prof` V8 snapshot, `--heap-prof-md`); the Claude Code zsh shims (grep/find → embedded ugrep/bfs) and macOS limits (no perf; `/usr/bin/time -l` instructions retired) |
| perf-bench | Interleaved A/B + bootstrap CI on the median ratio + Mann-Whitney + minimum effect gives trustworthy verdicts | Engine unit tests (statistics checked against hand calculations); a live run under load average 9 showed noise to 375% IQR/median and the top-up fix turning a 47% regression from "inconclusive" into "regressed" | The significance rule becomes ADR (a), decided by the owner. Add an instruction-count arm (macOS `/usr/bin/time -l`, Linux `perf stat`): measured CV here 0.05–1% vs 5–13% for wall time under load |
| perf-ci | Same-runner interleaved base-vs-head gate, policy from the base ref, budgets | Integration test: planted 3× regression fails, head-side policy loosening ignored; local run of suite+gate on a temp repo | Prove the gate both ways on a realistic fixture; governance (rigor profiles vs fixed defaults) becomes ADR (c) |
| perf-review | Frequency argument + measured confirmation for blocker/major findings; claims verified symmetrically | Eval `orders-pr-review`, one run per arm. **Both arms** found the N+1, the useless cache and the item-less-order crash. The skill run added interleaved A/B with CIs, scaling exponent, query counts, a claims table and a "checked and fine" section; the baseline was equally correct with fewer formal stats. Low discrimination: this fixture is too easy for a strong model | Treat as a weak signal; review moves out of round one. Consider merging review into a smaller skill set (Phase 3 choice) |
| perfkit (engine) | stdlib, vendorable; commands doctor/abtest/compare/hotspots/scaling/ledger/suite/gate | 32 tests on Python 3.9 and 3.12 | Add Quest/lore hooks to the ledger, an instruction-count metric, `.perf/` default paths; graders proven both ways |

## Eval status at audit time

Wave 1 (6 runs) launched before this review: PR review (both arms complete), Python optimisation and CI setup
(running). Wave 2 (TypeScript, Bash, browser) was cancelled. Round one of the revised skills will use 2–3
fixtures, one per stack, after the owner approves the run.

## Open questions put to the owner

1. ADR (a): statistical method and default significance rule.
2. ADR (b): default tool per stack.
3. ADR (c): governance, rigor profiles vs fixed defaults.
4. The final skill set: keep five, or merge.
