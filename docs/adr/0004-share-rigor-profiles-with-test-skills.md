---
# yaml-language-server: $schema=../../.lore/schemas/adr.schema.json
type: ADR
title: Share rigor profiles with test-skills
summary: "Use test-skills R1–R5 rigor profiles for performance claims; rigor means evidence strength, not effort."
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:02:14.315Z
---

# Share rigor profiles with test-skills

## Status

Accepted (2026-10-05, owner's choice: Option A).

## Context

test-skills defines R1 Minimal … R5 High-Assurance in `test-policy.toml`: effective rigor = max(project default, tier
of every touched path, declared rigor); levels raise evidence strength, never test count; agents can't waive
obligations at R4+ and can't approve at R5. The owner requires that performance rigor maps onto the same R1–R5
rather than inventing a parallel scale. The open question is **where the levels and their numbers come from**.

## Options

### Option A (recommended): one rigor source — test-policy.toml — plus a thin perf-policy.toml for perf-only numbers

- Rigor default and path tiers are read from `test-policy.toml` (`rigor`, `[[adequacy.tier]] paths/rigor`).
  `perf-policy.toml` holds only performance-specific settings: benchmarks, budgets, minimum effect, tolerances per tier.
  It may *raise* a path's rigor, never lower it.
- Each level maps to fixed obligations (perf-optimize `references/rigor.md`):
  - R1: one before/after;
  - R2: ≥5 runs, tests green;
  - R3: ≥10 interleaved, CI rule (ADR-0005), changed-path coverage before the change, ledger, hold-out;
  - R4: ≥20 runs, α = 0.01, mutation kill-matrix on the changed path before and after, differential equivalence,
    tail and memory gates, proof-skills hand-off for algorithm or concurrency changes, independent review;
  - R5: R4 plus a human approval the agent cannot give.
- **Trade-offs:** one vocabulary and one place to raise rigor across all three plugins, and the gate enforces it.
  Costs a dependency on test-skills' policy format; repos without test-skills get perf-policy defaults (R3).

### Option B: perf-policy.toml carries its own copy of R1–R5 settings

- The same level names, but each repository sets perf rigor and tiers independently in `perf-policy.toml`. test-skills
  is consulted only if perf-policy is absent.
- **Trade-offs:** no coupling to test-skills' file format, and perf tiers can follow benchmark names rather than
  paths. But the two levels can drift: a path can be R4 for tests and R2 for performance. That is the parallel scale
  the owner wants to avoid, only spelled the same way.

## Decision

Option A. Performance rigor uses test-skills' R1–R5. The project default and path tiers are read from
`test-policy.toml`; `perf-policy.toml` holds performance-only numbers and may raise a tier's rigor, never lower it.
Repositories without `test-policy.toml` default to R3.

## Consequences

- perfkit `gate` and `suite` resolve effective rigor as the max of: test-policy default, the test-policy tier of every
  path the benchmark protects (`[[tier]] paths` / `[[benchmark]] paths`), the perf-policy tier, and `--rigor`.
- perf-optimize's obligations per level (runs, α, coverage or kill-matrix before the change, hand-offs, review) are
  the single table in `references/rigor.md`, mirrored from test-skills' rigor spec.
- A change to rigor is a test-policy amendment (test-skills Article XIII), not a perf decision.
