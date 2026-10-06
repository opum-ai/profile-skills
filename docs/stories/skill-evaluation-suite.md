---
# yaml-language-server: $schema=../../.lore/schemas/arc.schema.json
type: Arc
title: Skill evaluation suite
summary: Six fixtures with objective graders run with and without the skills via skill-creator.
tasks:
  - pski-8
  - pski-9
  - pski-13
generated:
  by: lore/0.12.0
  at: 2026-10-05T19:02:15.244Z
lore_task_status: todo
---

# Skill evaluation suite

## Goal

Show what the skills add over a strong baseline, with graders that never trust the agent's claims.

## Acceptance criteria

- evals/ holds fixtures, evals.json, grade.py and setup_ws.sh
- Iteration results are recorded below

## Tasks

<!-- lore:tasks:begin -->
| Task | Title | Status |
|---|---|---|
| [PSKI-8](../../.quest/completed/PSKI-8.json) | Skill evaluation suite | Done |
| [PSKI-9](../../.quest/tasks/PSKI-9.json) | Optimize skill descriptions for triggering | To Do |
| [PSKI-13](../../.quest/completed/PSKI-13.json) | Prove graders and the perf-ci gate both ways | Done |
<!-- lore:tasks:end -->

## Notes

### Wave 1 (draft skills, 6 cases × 2 arms, one run each)

Both arms produced correct, similarly fast results on every case: Python optimisation (×120–176 at 60k rows), PR
review (both found the N+1, the useless cache and a crash bug), and CI setup. The skill runs added evidence, such as
hold-out workloads, mutation-checked equivalence harnesses and reported memory changes, at about 3–5× the time and
tokens. Two wave-1 runs found real bugs in the drafts: a `| tee` that could hide a failing gate, and the fallback TOML
parser mishandling `\"`. Both are fixed, with regression tests. A baseline run's paired Wilcoxon design was adopted
into perfkit (ADR-0005).

### Round one, first attempt (fixtures v1) — withdrawn

The Python pair repeated wave 1: both arms were equally correct (byte-identical on hidden inputs) and equally fast
(×121 vs ×125 on the hidden workload). The with-skill score was higher only because of the **process** assertions:
a saved profile, saved A/B evidence, and a reproducible claim. The owner rejected that as circular: it rewards the
skill's ritual, not better outcomes. Grading the real answers also exposed two grader false negatives (a claim
parsed from an unrelated sentence, and added tests counted as weakening), plus a claim format the parser missed.
All three were fixed and pinned with self-test variants. The TS with-skill run was stopped and round one restarted.

### Round one, redesign (fixtures v2, outcome-first scoring)

- **Headline = outcome assertions**, judged on the code left behind:
  - correct on hidden inputs and traps;
  - tests green, and not weakened;
  - faster than the original on a hidden workload;
  - **within 2× of an expert reference at 2× production volume**;
  - **meets the constraints stated** in the prompt or code.

  Process assertions (claim reproduced, profiler artefact, A/B evidence) are reported separately and never decide the
  comparison alone.
- **Fixtures v2 leave room for outcomes to differ** (each measured before use):
  - **Python:** an eager `log.debug(f"... {json.dumps(row)}")` becomes the dominant cost once the obvious set fixes
    are in. A stated 256 MB container limit at 2× volume rules out load-everything. The obvious fix alone reaches
    0.36× the expert's speed and 346 MB at 500k rows; the expert is 0.41 s and 139 MB.
  - **TypeScript:** the registry documents (and enforces) 16 concurrent requests. The algorithm-only fix reaches
    0.07× the expert; unbounded `Promise.all` crashes with HTTP 429. Graded on Node and Bun.
  - **Bash:**
    - The scary-looking per-key `grep` loop is a decoy: fixing it alone saves under 4%. The per-line forks are the
      cost; the expert is ×1800.
    - Mixed-case tenant paths make `LC_ALL=C sort` change the output under the documented `LANG=en_US.UTF-8`.
    - The stock ops-box environment (`/bin/bash` 3.2, `PATH=/usr/bin:/bin`) is checked.
- The graders are re-proven both ways on 19 variants, including the new partial, decoy, memory, overload and locale
  failures (`evals/selftest/`, results in `evals/results/`).

### Round one results (fixtures v2, final proven grader, one run per arm)

Graders were proven both ways before scoring:
- 19 known-good and known-bad answers give the predicted 171/171 cells;
- 18/18 assertion mutations flip exactly the predicted cells;
- results in `evals/results/round1-proofs/`.

Every grader change prompted by a real answer was pinned with a variant and re-proven before re-grading:
- a claim parsed from an unrelated sentence;
- added tests counted as weakening;
- per-step speedups treated as headline claims;
- Bun-only lines;
- "± spread (CPU)" table cells.

| Fixture | Arm | Outcome (6) | Process (3) | Speed vs expert at 2x volume | Other outcome metric | Tokens | Wall |
|---|---|---|---|---|---|---|---|
| Python report | with skill | 6 | 3 | 1.22 | peak RSS 108 MB at 500k rows | 214k (incl. 71k verifier subagent) | 28 min |
| Python report | without | 6 | 1 | 1.37 | peak RSS 88 MB | 73k | 11 min |
| TS resolver | with skill | 6 | 2 | Node 1.005 / Bun 1.005 | 16 in flight on both runtimes | 102k | 51 min |
| TS resolver | without | 6 | 1 | Node 0.995 / Bun 1.019 | 16 in flight on both runtimes | 39k | 6 min |
| Bash logs | with skill | 6 | 3 | 1.44 | stock-environment identical | 175k | 115 min |
| Bash logs | without | 6 | 0 | 1.74 | stock-environment identical | 133k | 23 min |

**Finding: no outcome difference.**
- **Outcomes:** both arms passed all 18 outcome assertions. On speed relative to the expert, the baseline was equal or slightly better on every fixture.
- **Where the skill differs:** in checkable evidence, with process scores of 8/9 vs 2/9. Its verifier subagent caught an inflated number (553 s claimed vs 179 s re-measured).
- **Cost:** 1.3–2.9× the tokens and 2.6–8.5× the wall time.
- **Harder fixtures didn't help.** The v2 fixtures were built to give outcomes room to differ (decoy hotspot, eager logging, a memory limit, a registry concurrency limit, a locale trap), and the baseline handled all of them. The Bash baseline even preserved more of the original's quirks than the expert reference.

**Implications:**
1. For a strong model, the skills' measurable contribution is verifiable evidence and claim honesty, not better code. Positioning should say so.
2. The cost is too high for that contribution. Candidates:
   - stop at the first large win when its gain already exceeds the target;
   - use fewer A/B runs when effects are 10× the noise (sequential stopping);
   - drop the verifier subagent below R4 (one run spawned it at R3);
   - shorten the per-experiment ledger ritual for obvious wins.
3. Outcome discrimination may need weaker models, much larger codebases (localisation is hard there, as in SWE-fficiency's 68% of gains in untouched functions), or tasks where the hotspot cannot be found by reading.
4. Several runs per arm are needed before any small outcome difference could be claimed.
