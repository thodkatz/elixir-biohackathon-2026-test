# 2026-11-10: experiments spec approval


**Unit:** `spec/experiments`, fork PR #84 (ready, label `spec`), worktree `.claude/worktrees/spec-experiments`.
**Spec:** `docs/specs/2026-11-10-experiments-design/` (README first: decisions 1–22, early output).
**Previous:** `docs/handoffs/2026-11-10T1029Z-experiments-spec-review.md` (the user's calls during writing).

## Where it stands

The review round is done: correctness and methodology reviewer subagents, 24 findings posted on #84
(comment 6765157294), all fixed in `4d084d4` and answered one line each (comment 6765215172). Rulings made there,
for the user to overrule on the PR: a preset builds its experiment's baseline arm; the gate learns a mitigation's
declared `probes`, and an undeclared closed probe in a participant arm is a note, not a refusal; `spe-eval`'s lock
carries a token so its own `spe-apply` calls pass; `mitigation: null` is a one-arm experiment (`ladder-l0`); the
no-provider-guard call is decision 22. The spec PR now waits on the gate: the user's `approved` label.

## Next

1. Woken by the gate watcher: `methodology gate clear 84`, read comments after the gate comment. A comment that
   changes a decision: amend the spec (no clarification needed before approval), reply, open the gate again.
2. Once `approved`: squash-merge (`gh api -X PUT repos/thodkatz/elixir-biohackathon-2026-test/pulls/84/merge -f
   merge_method=squash`; `gh pr merge` fails on this token, `docs/knowledge/gh-pr-create-token.md`), clean up the
   worktree and branch, move the pin in `biohackathon`, then `methodology next --unit plan/experiments <handoff>`.

## Watch for

- Another session pushed to this branch earlier (`c065eb1`): fetch before working, never force.
- `methodology gate approve` fails on this token: the user adds the label themselves.
