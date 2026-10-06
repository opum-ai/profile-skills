---
# yaml-language-server: $schema=../../.lore/schemas/arc.schema.json
type: Arc
title: perf-optimize skill
summary: Orchestrator for the recursive measure-profile-change-verify loop with guards, ledger, hold-out confirmation and stop rules.
tasks:
  - pski-3
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:02:14.571Z
lore_task_status: done
---

# perf-optimize skill

## Goal

Make agents optimize the real bottleneck, keep correctness, and stop on evidence instead of after the first win or a noisy 'speedup'.

## Acceptance criteria

- The loop requires a saved profile and Amdahl ceiling behind every change
- Every experiment is logged, including reverted ones
- Results are confirmed on a hold-out workload

## Tasks

<!-- lore:tasks:begin -->
| Task | Title | Status |
|---|---|---|
| [PSKI-3](../../.quest/completed/PSKI-3.json) | perf-optimize skill | Done |
<!-- lore:tasks:end -->

## Notes
