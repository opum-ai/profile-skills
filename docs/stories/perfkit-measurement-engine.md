---
# yaml-language-server: $schema=../../.lore/schemas/arc.schema.json
type: Arc
title: perfkit measurement engine
summary: "Stdlib engine: doctor, interleaved abtest, robust compare, hotspots for six profile formats, scaling, ledger, suite and gate."
tasks:
  - pski-2
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:02:14.452Z
lore_task_status: done
---

# perfkit measurement engine

## Goal

Give every skill one trustworthy way to measure, compare and read profiles.

## Acceptance criteria

- Commands doctor, abtest, compare, hotspots, scaling, ledger, suite and gate are documented in perf-bench/references/perfkit.md
- tests/ passes on Python 3.9 and 3.12, including an end-to-end planted-regression gate test
- hotspots reads pstats, .cpuprofile, Chrome traces, speedscope, folded stacks and bash/zsh xtrace

## Tasks

<!-- lore:tasks:begin -->
| Task | Title | Status |
|---|---|---|
| [PSKI-2](../../.quest/completed/PSKI-2.json) | perfkit measurement engine | Done |
<!-- lore:tasks:end -->

## Notes
