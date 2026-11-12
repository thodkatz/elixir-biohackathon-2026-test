# 2026-11-12: experiments track done (slice 7 merged, d021352)

**Unit:** slice 7/7, proven with an agent, fork **PR #95**, squash-merged as `d021352`. The unit's own record is
#95's body (tasks, rulings 1–6, both runs, the incident); the mid-unit handoff before it was
`docs/handoffs/2026-11-11T2242Z-experiments-slice-7-mid.md`. The track's *Current work* line is removed: all
seven slices of `docs/specs/2026-11-10-experiments-design/` are merged.

## What only the merge settled

- **Review round:** one local reviewer (correctness, methodology): one minor finding (switch to
  `experiment/<name>` in a `spe-x-<name>` workspace), fixed in `305d6bf`; two nits answered on #95.
- **Run 2's result:** `20261111T224004Z` (qwen3.8-27b, n=1): `trs-guard` unchanged, the model never tried the TRS
  write. A larger `--repeat` would say whether the guard does anything; not scheduled.
- **The incident:** after the `spe-x-trs-guard` rebuild the agent's push went to **upstream** (the VM key
  authenticates as kraatz; `docs/knowledge/agent-test-push-containment.md`). The user ruled it kraatz's to handle
  and drafted an upstream issue (they submit it from the browser: our token cannot reach the org). The stray
  upstream branch `experiment/trs-guard` stays until kraatz acts.
- **The VM** `denbi-agui-01` is restored to `instances/denbi.yml` (`create.yml` ok=171 failed=0, the clone on
  `main`, push URL the fork). The kraatz key is still on it.

## Next

No unit chained: the track is done. What is due on any track is in `BACKLOG.md`'s *Next*; the upstream port of
slices 1–7 (they are fork-only so far, and the portal follows upstream) is the obvious next track, for the user to
start.
