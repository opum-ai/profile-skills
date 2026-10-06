---
# yaml-language-server: $schema=../../.lore/schemas/adr.schema.json
type: ADR
title: Skill split - three skills by activity
summary: "Ship three skills: perf-optimize (the loop), perf-measure (profile, bench, verify, review) and perf-ci (policy and gate), sharing the perfkit engine."
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:02:13.881Z
---

# Skill split - three skills by activity

## Status

Accepted (2026-10-05, owner's choice: Option A, three skills). It supersedes the first draft's five-skill split.

## Context

The first draft shipped five skills: optimize, profile, bench, review and ci. The release review found:
- the best real-world prior art is one or two compact procedural skills: DataDog lading's hunt/review skills, and
  CodSpeed's single optimize skill;
- in wave-1 evals the separate review skill added little over a strong baseline;
- five overlapping trigger descriptions (profile vs optimize vs review) risk misrouting, and the measurement rules
  were duplicated across files.

## Options

- **A (recommended, chosen): three skills.**
  - perf-optimize: the recursive loop.
  - perf-measure: profile, bench, verify and review; every evidence task that doesn't change code.
  - perf-ci: policy, budgets, gate.

  Fewer, sharper triggers and one home for the measurement rules. `/perf-profile` and `/perf-bench` become modes.
- **B: keep five.** Explicit entry points and smaller files, at the cost of trigger overlap and rules kept in sync
  across five files.

## Decision

Option A. The engine (perfkit), `browser_trace.mjs` and `xtrace.sh` live in perf-measure's `scripts/`. perf-optimize
and perf-ci call them by path.

## Consequences

- The perf-profile, perf-bench and perf-review stories are superseded by the perf-measure story. Their tasks are
  closed as superseded by PSKI-4.
- Each skill's description names its two siblings for adjacent intents.
