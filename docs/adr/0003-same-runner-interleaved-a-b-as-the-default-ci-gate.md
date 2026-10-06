---
# yaml-language-server: $schema=../../.lore/schemas/adr.schema.json
type: ADR
title: Same-runner interleaved A/B as the default CI gate
summary: Gate PRs by building base and head in one job and comparing them interleaved with statistics; read the policy from the base ref.
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:02:14.172Z
---
# Same-runner interleaved A/B as the default CI gate

## Status

Proposed (awaiting the owner's decision; drafted before the release-quality review)

## Context

Shared CI runners vary 10–20% between jobs and CPU models behind one label differ (even instruction counts shift).
Comparing a PR's numbers with stored history from other runs produces flaky gates. Laaber et al. show that randomized
interleaving on the same instance detects ≤10% slowdowns. Instruction-count tools (CodSpeed simulation) are excellent
but Linux-only and blind to I/O.

## Decision

The default gate (`perfkit suite` + `perfkit gate`) checks out base and head, builds both, runs each registered
benchmark interleaved in one job, tops up runs while a result is inconclusive, and fails on regressions beyond the
tier tolerance, on inconclusive results whose point estimate exceeds tolerance, on output differences and on budget
breaches. The policy is read from the base ref (`--policy-ref`), so a PR cannot loosen its own gate. CodSpeed,
Bencher, github-action-benchmark, size-limit and LHCI are documented alternatives per metric.

## Consequences

- No external service is required; costs are 2× the benchmark time per PR, kept down by tier/path selection.
- Tolerances must be set from measured A/A noise on the runner class (documented in perf-ci).
