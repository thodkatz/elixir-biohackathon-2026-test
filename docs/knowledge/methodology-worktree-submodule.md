# `methodology worktree <branch>` in this submodule: worktree under `.git/modules/`, no claim

Seen 2026-11-08, claiming `change/agui-tool-group-steps` from the main checkout
(`/workspace/biohackathon/elixir-biohackathon-2026-test`, a submodule of `biohackathon`).

**Symptom.** `methodology worktree change/agui-tool-group-steps` printed a worktree path under the parent's git
directory, not under this checkout:

```
/workspace/biohackathon/.git/modules/elixir-biohackathon-2026-test/.claude/worktrees/change-agui-tool-group-steps
```

and opened no draft PR: its `gh pr create` stops on the organization token error (`gh-pr-create-token.md`).

**Cause.** In a submodule, `git rev-parse --git-common-dir` is `<parent>/.git/modules/<name>`, not
`<checkout>/.git`, so taking its parent as the main checkout lands inside the parent's `.git/modules/`. The path the
workflow expects is `<main checkout>/.claude/worktrees/<branch, / as ->` (`AGENTS.md`, *Claim before you work*).

**Fix: claim by hand.** Remove the misplaced worktree, then from the main checkout:

```bash
B=change/<slug>; W=.claude/worktrees/${B//\//-}
git worktree remove --force /workspace/biohackathon/.git/modules/elixir-biohackathon-2026-test/$W  # the misplaced one
git fetch origin && git worktree add -b "$B" "$W" origin/main
ln -s /home/agentvm/.local/share/agent-methodology/current "$W/.methodology"   # git-ignored, as in the main checkout
git -C "$W" push -u origin "$B"
gh api repos/thodkatz/elixir-biohackathon-2026-test/pulls -f title='…' -f head="$B" -f base=main \
  -F draft=true -f body='…' --jq .number
```

Copy the `.methodology` link target from the main checkout's own link (`readlink .methodology`). Until
`methodology worktree` resolves the main checkout with `git rev-parse --show-toplevel` (an agent-methodology change),
use these commands for every claim in this repo.
