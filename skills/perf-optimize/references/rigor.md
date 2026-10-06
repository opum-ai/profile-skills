# Rigor profiles for performance work

These are the same five levels as test-skills' engineering rigor profiles (R1 Minimal to R5
High-Assurance), applied to performance claims. **Rigor is evidence strength, not effort**:
a higher level asks for stronger proof that a speedup is real and harmless, never for more
micro-benchmarks.

**Effective rigor (ADR-0004)** is the highest of:
- `test-policy.toml`'s default, and the `[[adequacy.tier]]` rigor of every path you touch;
- any `perf-policy.toml` tier (which can only raise it);
- a `Rigor: R<n>` trailer or the Quest task's declared rigor;
- your own judgment.

Without `test-policy.toml` the default is R3. You may raise the level, never lower it. At R4/R5, missing evidence
blocks the result. It is not a footnote.

| Obligation | R1 | R2 | R3 (default) | R4 | R5 |
|---|---|---|---|---|---|
| Scope written (metric, workload, target) | in message | in message | `SCOPE.md` | + secondary metrics gated | + production-representative workload, signed off |
| Hotspot named from a saved profile | ✓ | ✓ | ✓ + Amdahl ceiling | ✓ + profile diff after | ✓ |
| Runs per arm | 1+ | ≥5 | ≥10, interleaved | ≥20, interleaved | ≥30, interleaved, repeated on a 2nd day/machine |
| Statistics (ADR-0005) | before/after | medians | paired ratio CI + Wilcoxon (interleaved), `min_effect` | α = 0.01; inconclusive blocks | as R4 + pre-registered targets |
| Behaviour pinned before the change | tests that exist | relevant tests green | + coverage of the changed lines (≥90%) + output equivalence on the workload | + tmx kill matrix on the changed code, no kills lost after; differential harness on randomized/edge inputs | + independent verification of equivalence |
| Hold-out confirmation | — | — | ✓ | ✓ + 2–4× larger size | ✓ + real production sample |
| Secondary metrics | — | note RSS | RSS + any gated metric | memory, p99/tail, startup not regressed | as R4, with budgets |
| Records (Quest notes + lore report) | — | Quest note | every experiment, kept and rejected | + predictions recorded before measuring | ✓ |
| Independent verification of the final claim | — | — | — | perf-measure verify mode in a separate context | ✓ |
| Concurrency or algorithm-equivalence changes (proof-skills hand-off) | note | note | race/property test, or formal-verify when the input space is large | formal-verify / lean-model required | + human review of the model |
| Review | — | self | self, with checklist | independent reviewer (perf-measure review/verify mode by a second agent counts) | accountable human approval; agent cannot self-approve |
| Rollout | — | — | — | feature flag or easy revert | flag + canary + rollback plan |

Notes:
- **Pre-registration** (R4+) means writing the predicted effect and the decision rule in the
  ledger *before* running the measurement, so a result can't be reinterpreted after the
  fact (HARKing).
- At **R5** the agent's role is to produce evidence. Whether to ship belongs to a person
  whose approval is recorded somewhere the agent cannot write: required reviewers or a
  protected environment, not a commit trailer.
- **R1** is for spikes: "Is this approach even in the right ballpark?" State the limitations
  ("single run on a laptop on battery"), and don't merge R1 numbers as claims.
