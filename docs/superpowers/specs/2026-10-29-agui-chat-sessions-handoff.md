# Handoff: AG-UI chat sessions spec (PR #7), session 1 → 2

Draft-only note (`sessions-and-context.md`, *Handing off mid-unit*); **delete this file in the commit that
addresses the review**, before #7 merges.

**Done.** Spec written and pushed (`ab3936f`); draft PR #7; `AGENTS.md` *Current work* line and
`docs/README.md` row added. Upstream checked on 2026-10-29: `upstream/main` (`baa5d54`) is fully in `main`,
nothing to merge; the diff touches nothing upstream changed.

**Not done / next task.** Address the local review round, then merge #7 and go on:

1. Review round: **done and posted** on #7 (comment `6493852838`): codex (correctness) 13 findings, agy
   (methodology) as `M1.`…, verbatim. The user's reviewer choice for later rounds: **codex and agy, opencode
   if one is out of quota** (`codex exec -s read-only -C <worktree> -o <out> - < prompt`;
   `agy -p "<prompt>" --mode plan`). Notable: codex 1–3 (volume ownership, two runs on one session,
   delete during a run) and agy M1 (the new volume breaks the canary ladder's slice-2 volume contract:
   update that plan per *Contract changes land too*).
2. Fix the findings, reply on #7 in one comment, one line per finding.
3. Fold in session 1's own finding (below) into decision 4 and §2/§3.
4. Mark #7 ready and **merge it yourself** (squash, `--signoff` not needed for squash via gh; DCO must pass).

**Decisions made in session 1 that the text doesn't show yet.**
- **The user approved the spec in chat** ("auto continue with the implementation of the spec", 2026-10-29),
  so the spec gate is passed once the review is addressed.
- **Merging: the agent merges the spec and plan PRs itself; the user merges every implementation slice PR**
  (they reach the Coder portal within minutes of a merge). Then continue: plan (`plan/agui-chat-sessions`,
  `writing-plans`), then slice 1, stopping after each slice PR is opened and reviewed.
- **Recorder (spec §2, Inputs for the plan) is settled by reading CopilotKit 1.79 / @ag-ui/client 1.0.2:**
  `AbstractAgent.clone()` copies `middlewares`, and `InMemoryAgentRunner.run` calls
  `request.agent.runAgent(...)`, which applies them. So AG-UI `Middleware` via `agent.use()` works; the
  plan's first task only pins it with a test.
- **Correction for decision 4:** the in-memory runner runs the agent *detached* from the browser's request
  (`runAgent()` is not cancelled when the client goes away). Closing the tab does **not** cancel the run: it
  runs to its end and is recorded `completed` (or `failed`). Only the stop button (`/stop` → runner `stop`)
  gives `cancelled`. Rewrite decision 4's check ("closing the tab mid-run still leaves the run's messages on
  disk" holds, with status `completed`) and §2 step 3 / §3 *During a run* accordingly.
- `platform/dev/fake_agent.py` has no slow run; decision 10's check needs one (e.g. a "slow" keyword).

**Check that proves the current state.** `gh pr view 7 -R thodkatz/elixir-biohackathon-2026-test` (draft,
one commit plus the claim); `python3 .methodology/shared/sync-agents.py --check` exits 0.

**Gotcha (not yet a knowledge note):** session 1 started in the parent `biohackathon` repo, so this repo's
`.claude/settings.json` hooks (context budget, methodology SessionStart) never loaded; it passed the 150k
budget unwarned. Start sessions for this work in the worktree (`continue.sh` does).
