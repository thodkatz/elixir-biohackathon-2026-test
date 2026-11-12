# 2026-11-12: mitigation names, review next

**Unit:** `change/mitigation-names`, fork **PR #96** (draft, label `change`). The session that started it hit its
context budget once the implementation was done; this hands the rest over.

## Where it stands

- **Asked by the user (2026-11-12):** the ladder's mitigations `L1`..`L5` say nothing about what they do; name
  them for it, keep the experiments `ladder-l0`..`l3`. Ids chosen by the user: `trs-read-only`, `data-tiers`,
  `egress-allowlist`, `typed-tools`, `answer-airlock`.
- **Done, by an implementer subagent:** `755fb96` (files, code, experiments, `closed_by` labels, tests) and
  `86c2218` (current-design docs, experiments spec clarification 5). A ladder mitigation is now one whose `on`
  sets a switch in `controls_asserts.LADDER` (`handoff.mitigation_switches`); `LADDER_IDS` is gone; `create.yml`
  keeps its own copy of the switch list, pinned to `LADDER` by a test; `validate.py` refuses `L<n>`/`l<n>` ids
  with a message; `matrix.py`'s `LEGACY_CLOSED_BY` reads old `L<n>` labels in stored results, so the committed
  `docs/results` matrix renders byte-for-byte unchanged. No `ladder:` field in the YAML (dropped on purpose: the
  order has one home, `LADDER`).
- **Checks, run by the subagent:** `validate.py` OK; `check_experiment.py` OK; `platform/dev/tests` 662 passed,
  1 skipped (template tests under tofu); `promptfoo-evals` 482 passed; `pydantic-ai-agent` 293 passed. No eval,
  no model call.
- **The subagent's open points** (decide in review): the Coder form now lists mitigations alphabetically, not in
  ladder order; the preset text reads `mitigation trs-read-only: TRS read-only` (id and name side by side); spec
  part 03 claims `check_experiment.py` refuses non-contiguous ladder mitigations but no such check exists (older
  than this change; the follow-up below removes contiguity altogether).

## Next, in this unit

1. Re-run the checks above in the worktree; write the PR body (plan, the rename table, checks run, the open
   points); mark ready (GraphQL `markPullRequestReadyForReview`: `docs/knowledge/gh-pr-create-token.md`).
2. Local review round: correctness and methodology reviewer subagents, findings as one PR comment; address them.
3. Merge (squash), clean up, move the pin in `biohackathon`.
4. Also on `main`, direct: *Current work*'s lines for kraatz #28–#32 are stale: all merged upstream (#31, #32
   inside #33), and #47 (evals via chat) too.

## Next track (the user, 2026-11-12): a spec, for the user to approve

Recorded in `BACKLOG.md`'s *Next*. In short, from the conversation:

- **No ladder levels.** A build is its mitigation set; the gate expects closed the union of the set's `probes`.
  `LADDER`, `PROBE_CONTROL`'s levels, `hardening.json`'s `level`, the leading-switch count and the participant-
  mitigation special case go. The user: "the set of mitigation is basically the ladder we dont need a separate id
  for that". Test case: `trs-read-only` + `egress-allowlist` passes the gate with no note (today it is level 1
  and `egress` closed reads as a mismatch).
- **All-on as the reference, one mitigation off per experiment** (leave-one-out), instead of the cumulative
  ladder: the deployment goal is everything on; each experiment answers "what do we lose without this one".
- **Tests tell both sides:** attack tests carry `closed_by` (leak returns when off); add a label for the utility
  tests a mitigation could break, so an experiment reports probes reopened, leaks returned, work broken or fixed.
  Two utility tests (`inventory-drs`, `run-smoke-genomes`) fail at every level on study-id canaries in DRS
  names: the study-id question in *Next* must be answered first (upstream's `leak-controls` exempts them).
- **Flaky counts** (2/5 vs 1/3): read <https://yasint.dev/write-an-eval-for-your-agent/> (the user's link) and
  turn it into a decision: repeats per arm, a difference reported only beyond the noise.

## Context the next sessions need (from this session's upstream check)

- Upstream `main` moved 49 commits; a merge conflicts in 11 files (`validate.py`, `agui_provider.py` and its test,
  `promptfoo-evals/README.md`, `platform/report/*`, Coder `main.tf`, `report.env.example`, copilotkit README and
  `live-sessions.ts`, the AG-UI spec's clarifications). Upstream's `validate.py` allows a trailing `## Evidence`
  section; without it our validator rejects 9 upstream threats.
- Unmerged upstream branches overlap ours: Yasin's `template/leak-controls` (hash-manifest `canary_check`, an agent
  guard and a proxy that know the planted canaries, on by default: it would make a canary evaluation pass by
  construction, against our airlock's decision 12); Josef's `evaluation-loop(-promptfoo)` (generative red-team
  loop; complementary: a confirmed attack can become an experiment's test; he keeps scenarios out of git).
