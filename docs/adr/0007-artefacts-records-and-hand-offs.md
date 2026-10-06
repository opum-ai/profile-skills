---
# yaml-language-server: $schema=../../.lore/schemas/adr.schema.json
type: ADR
title: Artefacts, records and hand-offs
summary: "Where profiler artefacts live and when they are cleaned up, how findings, baselines and rejected optimisations are recorded in Quest and lore, and when work is handed to test-skills, proof-skills and housekeeping-skills."
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:15:40.006Z
---

# Artefacts, records and hand-offs

## Status

Accepted (2026-10-05). Decided by the agent under the owner's release brief (Phase 2), from sibling conventions; the
owner may revisit.

## Context

The owner's brief requires:
- profiler artefacts have a home and a cleanup rule;
- each performance finding becomes a Quest task with its measurement attached;
- baselines and reports live in lore docs linked to the task;
- a rejected optimisation is recorded with its numbers;
- each skill names its hand-offs to test-skills, proof-skills and housekeeping-skills.

Inputs:
- **housekeeping-skills' `hk`:**
  - classifies ignored entries by basename;
  - treats names in `.housekeeping.toml [junk] patterns` that are ignored as `file.junk-ignored` (S1, trash, undoable,
    standard level);
  - treats unknown ignored files as S3, which needs a per-item disposition.
- **Quest:** supports `task edit --add-note` and `--doc`.
- **lore:** links Stories to tasks with `lore link`.
- **Heap snapshots** contain program data (possibly secrets or PII) and must never be committed.

## Decision

**1. Artefacts** (raw, regenerable, possibly large or sensitive) live in `.perf/<concern>/` at the repository root.
That covers profiles, traces, heap snapshots, flame graphs, abtest/compare JSON, the working ledger, and worktrees in
`.perf/wt-*`.
- `.perf/` is git-ignored. The skills add the ignore entry if it is missing.
- Cleanup rule: once the campaign's lore report and Quest notes are written, `.perf/<concern>` is disposable. Repos
  using housekeeping-skills add `".perf"` to `.housekeeping.toml [junk] patterns`, so `tidy` at the standard
  (task-done) level trashes it as S1, which is undoable.
- `perfkit doctor` warns when `.perf/` is not ignored or exceeds 500 MB.
- Nothing under `.perf/` is cited as the only copy of evidence.

**2. Records** (small, durable, reviewed):
- **Quest:**
  - every optimisation campaign, and every perf-review blocker or major finding, is a Quest task. Its description
    carries the measurement: ratio, CI, n, environment;
  - every experiment, kept or rejected, is appended to the task by `perfkit ledger add --quest-task <id>` as a note
    with its numbers;
  - rejected experiments are never deleted.
- **lore:**
  - the campaign report is a lore Reference, `Perf report: <concern>`, linked from the task with `quest task edit
    --doc`. It holds the baseline (environment, workload checksum, median/IQR), the experiments table (kept and
    rejected, with numbers), the hotspot summary before and after, remaining ceilings and caveats;
  - baselines that later changes are measured against are kept there, not in `.perf/`.

**3. Hand-offs:**
- **test-skills:**
  - before an optimisation, the changed path's behaviour is pinned: coverage of the changed lines (R3), plus a tmx kill
    matrix on the changed code before and after (R4+, test-audit's `tmx collect-pytest`, or Stryker import for JS);
  - characterisation tests that must be added go through test-plan's admission rules;
  - CI tiers for perf jobs follow test-ci.
- **proof-skills:** hand an invariant to formal-verify / lean-model / tlaplus-model instead of trusting tests when an
  optimisation:
  - changes a concurrency structure: threads, async fan-out, a removed or narrowed lock, batching that changes
    atomicity, or a cache shared across requests;
  - replaces an algorithm whose equivalence must hold for all inputs, such as incremental vs recompute or a custom
    index. This is required at R4+ and recommended at R3 when the input space is large and structured;
  - proof-simplify proves a guard or lock redundant before it is deleted for speed.
- **housekeeping-skills:** cleanup of `.perf/` and leftover worktrees, per rule 1. Long campaigns hand state across
  sessions through the Quest task notes and the lore report.

## Consequences

- Raw evidence can be deleted without losing the record, because reviewers read lore and Quest.
- perfkit gains `ledger add --quest-task`. The skills gain a "Records and hand-offs" section each.
- The integration is demonstrated on a real example in this repository (PSKI-12).
