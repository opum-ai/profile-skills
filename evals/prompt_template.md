You are working on a user's request in a repository. Execute the task fully and autonomously: no user is available to answer questions, so make reasonable decisions and state them.

Repository: {REPO}
Work only inside this directory (it is a git repository; you may create branches/commits, worktrees as siblings inside {OUTPUTS}, and temp files under {OUTPUTS}/tmp).
{SKILLS}
Environment: macOS arm64 (Apple M4, 10 cores). /bin/bash is 3.2 and no bash 5 is installed. Python: use `uv run --python 3.12 ...` (system python3 is 3.9). Node 24 is available. The Playwright npm package is installed at {PW}/node_modules (its Chromium is installed): use `export NODE_PATH={PW}/node_modules` or symlink that node_modules into a temp dir. Do NOT install anything system-wide (no brew, no sudo, no global npm installs); `uv run --with ...`, `uvx` and `npx` are fine. Other agents are running on this machine, so timings may be noisy.

The user's message:
---
{PROMPT}
---

When you are done, write the reply you would give the user into {OUTPUTS}/final_message.md and also return it as your final answer.
