#!/usr/bin/env python3
"""Prove the round-one graders both ways, then mutate them.

  GRADER_FAST=1 prove_graders.py <variants-dir> [--recollect]

1. Both ways: every variant from build_variants.py is graded. Each assertion must FAIL exactly on the variants
   EXPECTED lists for it and PASS on all the others, so the good answer passes everything and each bad answer fails
   its predicted subset.
2. Mutation: each assertion is replaced by a constant-True and then a constant-False stub. The cells that change must
   be exactly the predicted subset: True turns the variants that should fail it green, and False turns the variants
   that should pass it red. A mutation that changes nothing means the assertion discriminates nothing, which is a
   finding.

Facts are cached in <variant>/facts.json (collection is the expensive part); --recollect refreshes them.
Exit 0 only if every check holds. Writes <variants-dir>/proof.json.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import grade  # noqa: E402


def main(root, recollect):
    expected = json.load(open(os.path.join(root, "expected.json")))
    report = {"both_ways": [], "mutations": [], "ok": True}
    facts = {}
    for case, variants in expected.items():
        for v in variants:
            run = os.path.join(root, case, v)
            fpath = os.path.join(run, "facts.json")
            if recollect or not os.path.exists(fpath):
                print(f"collecting {case}/{v} ...", flush=True)
                json.dump(grade.collect(case, run), open(fpath, "w"), indent=1, default=str)
            facts[(case, v)] = json.load(open(fpath))
            # cheap facts are re-derived from the run directory on every proof, so parser fixes are proven too
            outputs = os.path.join(run, "outputs")
            msg = open(os.path.join(outputs, "final_message.md"), errors="replace").read()
            facts[(case, v)]["claims"] = grade.parse_claims(msg, grade.CASES[case]["markers"])
            cdef = dict(grade.CASES[case], name=case, ref=os.path.join(grade.FIX, grade.CASES[case]["fixture"]))
            facts[(case, v)]["tests_changed"] = grade.weakened_tests(cdef, os.path.join(outputs, "repo"))

    def matrix(assertions):
        return {(c, v): {r["text"]: r["passed"] for r in grade.evaluate(f, assertions)} for (c, v), f in facts.items()}

    base = matrix(grade.ASSERTIONS)
    for (case, v), row in base.items():
        must_fail = set(expected[case][v])
        for a, passed in row.items():
            want = a not in must_fail
            ok = passed == want
            report["both_ways"].append({"case": case, "variant": v, "assertion": a, "want_pass": want, "passed": passed, "ok": ok})
            if not ok:
                report["ok"] = False
                ev = [r for r in grade.evaluate(facts[(case, v)]) if r["text"] == a][0]["evidence"]
                print(f"✗ {case}/{v}: {a} passed={passed}, expected {want}  — {ev}")
    print(f"both ways: {sum(r['ok'] for r in report['both_ways'])}/{len(report['both_ways'])} cells as predicted")

    for a in grade.ASSERTIONS:
        for const in (True, False):
            mutated = dict(grade.ASSERTIONS)
            mutated[a] = (lambda f, c, k=const: (k, "mutated"))
            m = matrix(mutated)
            changed = sorted(f"{c}/{v}" for (c, v) in m if m[(c, v)][a] != base[(c, v)][a])
            predicted = sorted(f"{c}/{v}" for (c, v) in base
                               if (a in expected[c][v]) == const)   # True flips the should-fail; False flips the should-pass
            ok = changed == predicted and bool(changed)
            report["mutations"].append({"assertion": a, "constant": const, "changed": changed, "predicted": predicted, "ok": ok})
            mark = "✓" if ok else "✗"
            print(f"{mark} mutate {a} -> {const}: {len(changed)} cells changed (predicted {len(predicted)})")
            if not ok:
                report["ok"] = False
    json.dump(report, open(os.path.join(root, "proof.json"), "w"), indent=1)
    print("PROVEN" if report["ok"] else "NOT PROVEN")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(os.path.abspath(sys.argv[1]), "--recollect" in sys.argv))
