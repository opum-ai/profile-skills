#!/usr/bin/env python3
"""perfkit: measurement engine for profile-skills. Stdlib only, Python 3.9+.

  doctor     tools available, plus warnings about benchmark noise on this machine
  abtest     interleaved A/B of commands; checks the arms print identical output
  compare    median ratio with bootstrap CI, Mann-Whitney U, verdict at a minimum effect
  hotspots   top frames by self/total time from pstats, .cpuprofile, Chrome traces,
             speedscope, folded stacks or bash xtrace; --diff for before/after
  scaling    time vs input size, log-log exponent (empirical big-O)
  ledger     experiment log for the optimization loop (add / show)
  gate       enforce perf-policy.toml (regression tolerances, budgets) in CI
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from perfkit.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
