# 2026-11-12: mitigation names merged; next track waits on the user


**Unit:** `change/mitigation-names`, fork PR #96, **merged** (squash `3db0002`). The unit's own handoff:
`docs/handoffs/2026-11-12T0104Z-mitigation-names-review-next.md` (its *Next track* and upstream context still hold).

## What the merge settled

- **Review round** (local, correctness + methodology; comment issuecomment-6811462503): 5 findings. Fixed in
  `8fac694`: spec part 03 now names `create.yml` for the contiguity check; the knowledge note's example names
  `trs-read-only.yml`; `mitigations/TEMPLATE.yml` says an `on` setting a `LADDER` switch makes a ladder mitigation.
  Deferred to the level-free experiments track (its `BACKLOG.md` *Next* line): the form lists mitigations
  alphabetically (ladder reversed); `matrix.py`'s `render` doesn't map old `L<n>` `closed_by` labels.
- **Checks:** all green except one `platform/dev/tests/test_hardening.py::test_hardening_json[overrides4-0]` failure
  in the full run while reviewers ran tests in parallel; alone it passed 4 runs of 4. Read as load flakiness; if it
  fails again unloaded, debug it.
- **Direct on `main`:** `997a495` drops *Current work*'s stale kraatz #28–#32 lines.
- `methodology worktree --prune` can't read the forge: the upstream org refuses the fine-grained token (lifetime
  over 366 days); only worktrees whose remote branch is gone are pruned. Fork operations work.

## Next

No unit chains on: the next track is the level-free experiments **spec**, written with the user (brainstorming) and
approved by them, and it first needs their answer to the study-id question (`BACKLOG.md` *Next*). Start it when the
user is in the session.
