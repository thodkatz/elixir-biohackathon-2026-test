# 2026-11-13: merge upstream review


**Mid-unit handoff (context budget).** Unit: step 1 of the *Reconciliation plan*
(`docs/investigations/2026-11-12-upstream-reconciliation.md`), merging `upstream/main` (`9bff54c`) into `main`.
Branch `change/merge-upstream-2026-11-12`, worktree `.claude/worktrees/change-merge-upstream-2026-11-12`, draft PR
**#97** (label `change`). The PR body holds the plan, the rulings and the checks that ran.

## Done

- Merge commit `b3f9e48`: 18 conflicts resolved; how each was resolved is in its message. Pushed.
- Every *Running things* command passes (report tests now need `--with pyyaml`; AGENTS.md updated).
- `methodology sync --check`: clean.
- `gh pr create` / `gh pr merge` fail on the token (`docs/knowledge/gh-pr-create-token.md`); #97 was opened with
  `gh api …/pulls`. `methodology worktree --prune` can't read the forge for the same reason.

## Next

1. The local review round on #97 (*Reviewers*: correctness and methodology focuses, findings as one PR comment).
   Worth a close look: `sperange_report.py` (both route sets, `page()`'s scripts, `make_server`'s new `hits_dir=`
   keyword), `agui_provider.py`, `validate.py`'s optional trailing heading, and the methodology focus on
   docs the merge left stale (e.g. `docs/README.md`, `platform/report/README.md`'s *Running and testing*, which
   lacks `HITS_DIR`).
2. Address the findings, mark #97 ready (GraphQL `markPullRequestReadyForReview`, see the knowledge note), and
   merge with a **merge commit**: `gh api -X PUT repos/thodkatz/elixir-biohackathon-2026-test/pulls/97/merge -f
   merge_method=merge`. DCO stays red over upstream's unsigned commits; say so.
3. Cleanup, the pin in `biohackathon` (it trails at `b720ace`; move it to the merged `main`), and the track's
   unit-end handoff. Step 2 of the plan (who raises the method points upstream) waits on the user.
4. Unscheduled from this unit, for `BACKLOG.md` when merging: a chat stem comes from the chat's title, so a
   canary in a title would land in a runs-API URL (`test_no_route_takes_a_token` now skips the API's archive-name
   parameters). Also, `trs-guard`'s `conflicts: [L1]` sits on upstream's `experiment/trs-guard`, which our
   token can't push to.
