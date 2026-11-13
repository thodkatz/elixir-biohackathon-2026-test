# 2026-11-13: merge upstream merged



**Unit end.** Step 1 of the *Reconciliation plan* (`docs/investigations/2026-11-12-upstream-reconciliation.md`) is
done. #97 merged `upstream/main` (`9bff54c`) into `main` as merge commit `11d7bfe` (a merge commit, per *Overrides*).
The unit's own handoff, `2026-11-13T0002Z-merge-upstream-review.md`, says how the merge went. Read this one only.

## What the merge settled

- The local review round (correctness, methodology, report service) found 15 items. None is a merge bug. The fixes
  are `68840bc` (`runs`/`api/` dispatched before the hits routes, the API placeholders pinned, and a target key
  test) and `9defa26` (stale docs). Every deferred item is in `BACKLOG.md` *Unscheduled*, under "Runs browser: …",
  `trs-guard`'s conflicts and the fork-only link in `platform/ansible/README.md`.
- DCO stayed red over upstream's unsigned commits, and the PR was merged anyway, as its body says.
- The worktree and branch are removed. The pin in `biohackathon` moves to this handoff's commit.

## Next

Nothing is due without the user. The reconciliation's step 2, deciding who raises the method points with Yasin,
Kraatz and Josef, waits on them (`BACKLOG.md` *Next*). So do three of the runs-browser items, and the "close the
loop" spec after it. The track ends here (`methodology next --end`).
