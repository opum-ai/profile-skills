---
# yaml-language-server: $schema=../../.lore/schemas/arc.schema.json
type: Arc
title: perf-measure skill
summary: "Gather performance evidence without changing code: profile, bench, verify a claimed speedup, review a diff; one decision rule (ADR-0005) and best-of-breed tools (ADR-0006)."
tasks:
  - pski-4
supersedes:
  - stories/perf-bench-skill
  - stories/perf-review-skill
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:02:14.705Z
lore_task_status: done
---

# perf-measure skill

## Goal

Answer "where does the time go", "is B faster", "is this speedup real" and "will this diff regress" with evidence,
using one decision rule across Python, Node, Bun, browser and Bash. This merges the drafted perf-profile, perf-bench
and perf-review skills (owner's Phase 3 choice; ADR-0001).

## Acceptance criteria

- Four modes (profile, bench, verify, review) share the ADR-0005 rule and the ADR-0006 tools
- Profiling guidance per runtime, including Bun's measured overhead and idle-time caveat
- Records and hand-offs name Quest, lore, test-skills, proof-skills and housekeeping-skills (ADR-0007)
- browser_trace.mjs and xtrace.sh produce files that perfkit hotspots reads

## Tasks

<!-- lore:tasks:begin -->
| Task | Title | Status |
|---|---|---|
| [PSKI-4](../../.quest/completed/PSKI-4.json) | perf-measure skill (profile, bench, verify, review) | Done |
<!-- lore:tasks:end -->

## Notes
