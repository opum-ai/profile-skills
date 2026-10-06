---
# yaml-language-server: $schema=../../.lore/schemas/arc.schema.json
type: Arc
title: perf-ci skill
summary: Perf policy with rigor tiers and budgets, and a same-runner interleaved base-vs-head CI gate that a PR cannot loosen.
tasks:
  - pski-6
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:02:14.981Z
lore_task_status: done
---

# perf-ci skill

## Goal

Catch performance regressions in PRs without flaky wall-clock comparisons.

## Acceptance criteria

- perf-policy.toml, GitHub Actions, LHCI and agent-block templates exist
- The gate reads the policy from the base ref and is demonstrated failing on a planted slowdown

## Tasks

<!-- lore:tasks:begin -->
| Task | Title | Status |
|---|---|---|
| [PSKI-6](../../.quest/completed/PSKI-6.json) | perf-ci skill | Done |
<!-- lore:tasks:end -->

## Notes
