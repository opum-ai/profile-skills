# Trigger-description evals (PSKI-9), 2026-10-20

Per skill: a 20-query trigger set (`evals/trigger/<skill>.json`: 10 should-trigger, 10 near-misses drawn from the two
sibling perf skills and the proof/test territory), split 12 train / 8 held-out (stratified, `--holdout 0.4`), each
query run 2 times, 3 improvement iterations. Raw output: `<skill>.results.json` in this directory. (Kept beside the sets they score, not in `evals/results/`, which holds the round-1 proofs.)

## How it was run

- Runner: skill-creator `scripts/run_loop.py`, plugin cache copy `315c4e48967d`, Python 3.12.
- Model: `claude-sonnet-5-5` pinned for both the `claude -p` trigger children and the description improver.
  `claude --version` 2.1.299.
- Each loop ran from its own empty neutral directory (only `.claude/`), so this repository's symlinked skills in
  `.claude/skills/` could not compete with the candidate and the three loops could not see each other's candidates.
- `--runs-per-query 2 --num-workers 6 --max-iterations 3 --trigger-threshold 0.5 --timeout 30`.
- Iteration 1 evaluates the unchanged description, so its held-out score is the baseline.

## Held-out scores (8 queries each)

| Skill | Baseline (iter 1) | Iter 2 | Iter 3 | Best by loop | Adopted |
|---|---|---|---|---|---|
| perf-ci | 5/8 | 5/8 | 5/8 | 5/8 (baseline) | no change |
| perf-measure | 4/8 | 7/8 | 4/8 | 7/8 (iter 2) | no change, see below |
| perf-optimize | 4/8 | 5/8 | 4/8 | 5/8 (iter 2) | no change, see below |

Train scores (12 queries): perf-ci 8, 9, 8; perf-measure 8, 8, 7; perf-optimize 7, 7, 8.

## Reading the numbers

- Recall is the weak side everywhere. Basis, train split only (the loop prints precision and recall for train, not
  held-out): in the perf-ci loop, run-level (24 runs per iteration) precision was 100% and recall 17-25%; at query
  level, across all three loops and all iterations, 1-3 of the 6 should-trigger train queries passed and no
  should-not-trigger train query false-triggered. Headless `claude -p`
  with one command available rarely reaches for a skill unless the task clearly needs one, so a lot of should-trigger
  queries never trigger whatever the description says. Near-miss negatives almost never false-trigger.
- A held-out set of 8 queries x 2 runs moves by 3 points between iterations of near-identical descriptions
  (perf-measure 7/8 then 4/8). The loop's "best" is chosen by held-out score, which also makes it optimistic.
  The perf-measure iter 2 result is therefore not read as an improvement, and no description was changed. Train
  scores did not move for it (8/12 both).
- `best_description` and `final_description` in each results file are candidates, NOT adopted: every SKILL.md still
  carries its `original_description`.
- Candidates are in each results file (`history[].description`). If one is wanted, re-score it against the baseline
  with more runs per query on the full 20 queries before adopting.
