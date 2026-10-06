# Records, artefacts and clean-up (ADR-0007)

## Where things live

| What | Where | Lifetime |
|---|---|---|
| Raw artefacts: profiles, traces, heap snapshots, flame graphs, abtest/compare JSON, the working ledger, SCOPE.md, equivalence harness | `.perf/<concern>/` (git-ignored) | disposable once recorded |
| Worktrees for the incumbent / candidates | `.perf/wt-<name>` (`git worktree add .perf/wt-incumbent HEAD`) | removed at the end (`git worktree remove`) |
| The campaign and its experiments | Quest task (description = scope; one note per experiment) | permanent |
| Baseline, results, rejected attempts, remaining hotspots | lore Reference `Perf report: <concern>`, linked from the task | permanent, reviewed |
| Kept code changes | commits `perf(<concern>): E<n> …` | permanent |

Setup:
```bash
grep -qxF '.perf/' .gitignore 2>/dev/null || echo '.perf/' >> .gitignore
mkdir -p .perf/<concern>
```
Heap snapshots and traces can contain secrets or personal data. Never commit them, and
never paste their contents into Quest or lore. Summaries only.

## Quest

```bash
quest search "<concern>" --json                       # reuse an existing task
quest task create "Perf: <concern>" --json --label perf \
  --description "Metric: … Workload: … (sha256 …) Hold-out: … Target: … Rigor: R3 Baseline: median … (IQR …, n=…, env …)" \
  --acceptance-criteria '["Target met on main and hold-out workloads, or a stop rule recorded","Tests green; equivalence harness 0 diffs","Lore report linked"]' \
  --actor <agent> --actor-kind delegated-agent --accountable-human <human>
export PERFKIT_ACTOR=<agent> PERFKIT_ACTOR_KIND=delegated-agent PERFKIT_ACCOUNTABLE_HUMAN=<human>
python3 $PK ledger add .perf/<c> --id E1 ... --quest-task PSKI-42      # appends: "perf E1 [kept] …: −41.2% (ratio CI …, p=…, n=[20, 20]) guard: …"
```
`ledger add --quest-task` exits 3 (and prints why) if Quest or the actor variables are missing.
In that case add the note by hand with `quest task edit <id> --add-note "…"`. Kept **and**
rejected experiments are both recorded.

Each perf-measure review blocker or major becomes its own task, with the measurement in the
description.

## lore

```bash
lore query "perf report <concern>" --limit 3          # an earlier report to compare against?
lore new reference "Perf report: <concern>" --summary "<one-line result>" --tags perf
python3 $PK ledger show .perf/<c>                      # markdown table of every experiment → paste into the report
quest task edit <id> --doc reference/perf-report-<concern> --actor … --actor-kind … --accountable-human …
lore check
```
The report follows `report.md`. The baseline table in it is what later changes measure
against, so record the environment and the workload checksum.

## Clean-up

When the task is done and the report is linked:
- `git worktree remove .perf/wt-*`.
- `.perf/<concern>` is disposable. In repos using housekeeping-skills, add `".perf"` to
  `.housekeeping.toml [junk] patterns`. `tidy` at the standard level then trashes it as S1,
  with an undo through the Trash. Otherwise tell the user it can be deleted.
- Nothing under `.perf/` may be the only copy of evidence the report cites.

## Worked example

This repository's own `docs/reference/perf-report-*.md` and the linked Quest task show a real
campaign end to end.
