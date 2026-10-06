---
# yaml-language-server: $schema=../../.lore/schemas/arc.schema.json
type: Arc
title: perf-review skill
summary: Review diffs for performance risk with frequency arguments and measured confirmation; verify claimed speedups.
status: deprecated
tasks:
  - pski-7
superseded_by: stories/perf-measure-skill
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:02:15.112Z
lore_task_status: done
---

# perf-review skill

## Goal

Find the regression that matters, confirm it, and skip nitpicks on cold paths.

## Acceptance criteria

- Anti-pattern catalogs for Python, JS/TS, browser, Bash and data access exist
- Blocker/major findings require a frequency argument and preferably a measurement

## Tasks

<!-- lore:tasks:begin -->
| Task | Title | Status |
|---|---|---|
| [PSKI-7](../../.quest/completed/PSKI-7.json) | perf-review skill | Closed |
<!-- lore:tasks:end -->

## Notes
