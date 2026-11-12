# 2026-11-11: experiments slice 7, mid-unit (context budget)

**Unit:** slice 7/7, proven with an agent (decision 20), branch `impl/experiments-7-proven-with-an-agent`, draft
**PR #95** (opened over REST, label `impl`). Unit scope: `docs/handoffs/2026-11-11T2026Z-experiments-slice-7.md`.
Ledger (rulings 1–5, run 1, what was fixed): `.superpowers/sdd/slice7/progress.md` in this worktree (git-ignored;
its rulings go into #95's body). Slice 6's worktree is pruned.

## Where it stands

- **The workspace:** `denbi-agui-01` (agent-service-1), built from this branch's code, with the experiments
  template's rendered `build_vars` (`.superpowers/sdd/slice7/*.yml`; `qwen.yml` puts the SPE agent on de.NBI
  `qwen3.8-27b`, free). Its clone's `origin` push URL is a bare repo on the VM, `~/push-relay.git` (no portal SSH
  key); relay a branch with `git fetch ssh://agent-service-1/home/ubuntu/push-relay.git <b>:refs/remotes/relay/<b>`
  and `git push origin relay/<b>:refs/heads/<b>`. **Never relay** the relay's `impl/experiments-7-…` branch (the
  agent's mistaken first commit).
- **Run 1 (a fresh Sonnet subagent, from the sentence alone):** reached `experiment/trs-guard` at `d8b37ca`
  (relayed to the fork): new injection `trs-guard`, detector `_trs_write` in `metrics.py`, guard `trs_guard.py`
  behind Traefik, probe `trs-write-sensitive.sh`; `check_experiment.py trs-guard` exits 0, `spe-eval pr-body`
  printed. `spe-eval arm trs-guard mitigated` refused on creation-time settings (the new injection), as decision 7
  intends. Its stumbles are fixed in `300a2c3` (the refusal names `experiment/<name>` and `spe-x-<name>`) and
  `842da87` (workspace guide: branch first, the refusal's next step, `spe-eval arm` over `spe-apply -e k=v`, a
  guard sees the seeding writes, a probe's controls entries); dev tests 659 passed / 1 skipped.
- **Run 2, in progress:** the VM was rebuilt as a `spe-x-trs-guard` workspace (ruling 5: the person's dashboard
  step, done by the session) and the agent resumed with one message saying so. It started
  **`spe-eval run` 20261111T224004Z** (detached, a user systemd unit on the VM: it finishes without this session).
  The subagent itself ended with this session: its final report is lost.

## Next

1. `ssh agent-service-1 'spe-eval status; spe-eval results --run 20261111T224004Z; cd ~/sperange && git status
   --short && git log --oneline -3'`. If the run failed, read `spe-eval status`'s last error and fix what is ours.
2. Decision 20 asks the agent to finish: start a fresh subagent with `.superpowers/sdd/slice7/agent-prompt.md`
   plus one line ("the workspace is built from spe-x-trs-guard; run 20261111T224004Z measured it; finish: commit,
   check, push, pr-body with the result"), and collect its stumbles. Then relay `experiment/trs-guard` again.
3. Fix what it stumbled on (guide or command); rerun only what changed.
4. Restore the VM: `create.yml` from the main checkout with `instances/denbi.yml` (`denbi-anthropic-haiku.md`).
5. #95's body (title `Experiments: proven with an agent (7/7)`; tasks, rulings 1–5, both runs, checks), the
   *Current work* line removed (last slice), the local review round, checks (*Overrides*), merge over REST,
   cleanup, the pin in `biohackathon`; the track ends with `methodology next --end`.

The de.NBI key: hash-checked from the `thodkatz/test` Coder workspace (`denbi-llm-key.md`), exported per run only.
