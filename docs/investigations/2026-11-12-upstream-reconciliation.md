# Reconciling the fork with upstream (2026-11-12)

**Question.** Where do our fork's approach and upstream's differ, what does the fork bring that upstream lacks (and
the reverse), where do the two collide, and in what order do we reconcile them?

**Basis.** The comparison from session `b7b3651e` (2026-11-12, 01:05), re-checked claim by claim against upstream as
fetched at 08:30: `upstream/main` = `847842f` (unchanged since that session), merge base `c42e31b`, and the
unmerged branches below. Each claim was verified with `git show`/`git merge-tree`, and the threat-schema claim by
running our `validate.py` on upstream's `threats/` in a scratch worktree. Corrections to the first session are
marked **(corrected)**.

**Size of the divergence.** Since `c42e31b`: upstream 32 commits, 83 files, +5.0k lines; our fork 325 commits,
708 files, +86k lines.

## Who is doing what upstream

| Branch (merged?) | Author | What |
|---|---|---|
| `main` | Kraatz, josefaugustin, tammy357, Sampsa Penna, us | 12 new threats, `## Evidence`, the runs browser, our ports #28–#33 and #47 |
| `template/canary-guard` (merged as #41) | tammy357, Yasin | `canary_check` (hash manifest), the canary-guard proxy |
| `template/leak-controls` (not merged; 17 commits) | Yasin | the agent guard, hash-based promptfoo grading, honeypot file masks, Open WebUI and 3 tools dropped, client tools discarded |
| `evaluation-loop`, `evaluation-loop-promptfoo` (not merged) | josefaugustin | threatlab: a generative red-team loop |
| `threat-evals-josef` (two commits unmerged) | josefaugustin | TM-018/019, with the id bug below |
| `experiment/trs-guard` | **us** (corrected: not a stray) | a `trs-guard` mitigation; its `conflicts: [L1]` is stale after 3db0002 |
| `template/extend-promptfoo-evals` | — | equals `main`, a portal-template branch only |

## The difference in approach

- **Upstream detects and blocks; the fork measures.** Upstream has a checker (`canary_check`) and two guards (the
  proxy, the agent guard) as template-wide switches. The fork has a controlled, repeatable before-and-after
  comparison: planted canaries and injections, a fresh state per test, a controls gate that proves a mitigation is
  on before a model runs, metrics that separate `touched` / `answer` / `sent` / `delivered` /
  `injection.followed` / utility, and experiments as declarative files (threat × path × mitigation × attack).
  None of the measurement exists upstream.
- **Josef searches; the fork measures.** threatlab asks *is there an attack that works?* (one arm, generated
  attacks, judge plus thresholds, replay to confirm); the fork asks *does this mitigation help, by how much?* (two
  arms, committed attacks). They hand off: a confirmed attack becomes an experiment's attack.
- **Upstream keeps attacks off git; the fork commits everything.** Josef's `354c8c9` untracks the scenarios ("the
  catalog ships in the repo, the probes and the runner stay on the operator's machine"). Experiments rest on the
  attack, mitigation and tests being files anyone can rerun.

## Collisions, checked

1. **The guard knows the canaries; the airlock deliberately does not.** Yasin's agent guard (`spe_agent/guard.py`,
   `enforce` by default since `d993465`) and the proxy match against the planted-canary manifest. Our spec decision
   12 (`docs/superpowers/specs/2026-10-22-canary-eval-ladder-design/README.md:35`): a filter that knows the
   planted values passes the evaluation by construction. A good guard, but a canary evaluation with it on measures
   its own list. **Needs a decision with Yasin and Kraatz.**
2. **Study ids.** Upstream exempts `registry-study-id` by default in both guards and in its grading
   (`group_vars/all.yml:137`, `asserts.py:143`: study ids are part of the DRS names the agent must use). That is
   our open `BACKLOG.md` question, answered *no, not a disclosure*. Our airlock redacts `STUDY-` ids by pattern.
3. **Four canary matchers.** Ours (`canarymatch.py`, plus `canary_watch.py` and `canary_record.py` reading the
   plaintext `canaries.json`) (corrected: not only `canarymatch.py`); `canary_check`; the guard; the proxy, each
   re-implementing JSON-escape decoding. Theirs never needs the plaintext.
4. **Overlapping defences.** Their honeypot file masks overlap our `data-tiers`; dropping Open WebUI and 3 tools
   overlaps `typed-tools` and our frontends; the proxy is a different defence against TM-001 than our
   `trs-read-only` / `data-tiers` / `egress-allowlist`. None is a `mitigations/*.yml`, so none can be measured as an
   experiment.
5. **Scoring vocabularies.** Josef's `{nonce}` payloads and `checks.py` indicators vs our canary metrics: a threat's
   `## Evidence` and an experiment's result say "worked" differently.
6. **`agui_provider.py`.** Josef's `chat_body` sends `forwardedProps: {}`; ours sends `spe_source: eval`. Taken as is,
   eval runs would count as the participant's canary hits again.
7. **Josef's TM-018/019 carry `id: TM-015`/`TM-016`** inside the files (`81c9cbf` renamed the files only); both fail
   `validate.py`.
8. **Run archive permissions.** Upstream `main` makes the run archive world-readable (0700 → 0755, 0600 → 0644) so
   the report service can serve it. Security-relevant; check it against our TM-005 conversation record before
   taking it.

## Merge conflicts

- **`upstream/main` into our `main`: 11 files** (confirmed): `validate.py`; `promptfoo-evals/{agui_provider.py,
  tests/test_agui_provider.py, README.md}`; `report/{sperange_report.py, README.md}` (their runs browser vs our hit
  viewer); `coder/template/main.tf`; `coder/deploy/report.env.example`; `copilotkit-chat/{README.md,
  lib/live-sessions.ts}`; the AG-UI spec's `clarifications.md`.
- **The threat schema** is the one real conflict in the catalogue: our refactored `check_body_headings` has no
  `## Evidence` allowance. Without it, 9 upstream threats fail and, through them, all four `ladder-l*` experiments
  (`unknown threat 'TM-001'`). With it (threats only, since paths share the check): 16 threats, 4 paths,
  5 mitigations, 4 experiments validate, and `check_experiment.py` is clean. TM-006…017 need no new fields to
  appear in experiments, only paths, tests and possibly mitigations.
- **If `leak-controls` merges upstream first, 6 more files conflict** (corrected: the first session listed 5):
  `spe_agent/app.py`, `group_vars/all.yml`, `frontend.env.j2`, `workflow_stack/tasks/main.yml`,
  `compose.install.yaml.j2`, and `promptfooconfig.yaml` (modify/delete: we deleted it in #64).
- **`evaluation-loop-promptfoo`** conflicts in 12 files, mostly the same ones plus `AGENTS.md`.

## What each side brings

**The fork brings** (none of it upstream, see `docs/upstream-ports.md`):
- the canary ladder's measurement: scoring and metrics, isolation (snapshot, restore, state diff), the controls
  suite and gate, planted injections and the test receiver, the agent suite, the mitigations as Ansible switches,
  the L5 airlock, and measured results (`docs/results/canary-ladder-qwen3.8-27b.md`);
- the canary hit viewer (its upstream branch `contrib/canary-hit-viewer` is ready; the PR waits on the user);
- ladder replay (#83);
- the experiments track: paths, mitigations and experiments as files, `spe-eval`, the spe-experiments template,
  the contribution flow.

**Upstream brings:** 12 threats with evidence; the runs browser; the guards and the hash-only matcher; the file
masks; threatlab. Of these, the fork lacks all but our own ports.

**The port ledger is stale.** `docs/upstream-ports.md` still shows kraatz #28–#32 as open (merged), and has no lines
for "leave a running chat" (in kraatz #33) or "evals through the chat server" (`e841b64`, kraatz #47).

## Reconciliation plan

Order matters: each conflict grows the longer we wait, and `leak-controls` landing upstream adds six.

1. **Merge `upstream/main` into our `main` now** (a change PR, merged with a merge commit, *Overrides*).
   - `validate.py`: add the `## Evidence` allowance to `check_body_headings` for threats only, with a test.
   - `agui_provider.py`: keep our `_run`, 503 retry and `spe_source: eval`.
   - `sperange_report.py` / `report/README.md`: keep both the runs browser and the hit viewer.
   - Review the archive permission change (collision 8) before taking it.
   - In the same PR: the ledger's stale lines, and `trs-guard`'s `L1` → `trs-read-only`.
   - Checks: every command in `AGENTS.md`'s *Running things*.
2. **Settle the method points with upstream before porting more.** A short note per audience, which the user
   sends or raises:
   - Yasin and Kraatz: (a) one canary matcher, theirs (hash manifest) as the base, ours adapted to it; (b) a guard
     that knows the canaries is a control to *deploy*, not to *evaluate with*: measure it as a `mitigations/*.yml`
     against canaries it was not given, or count it as a detective control; (c) their guards and masks become
     mitigation files, so experiments can measure them.
   - Josef: (a) a confirmed threatlab attack can become a committed experiment (the git question); (b) a shared
     verdict vocabulary between `## Evidence` and experiment results; (c) `chat_body` must keep `spe_source: eval`;
     (d) the TM-018/019 id bug.
3. **Port the fork's work upstream, smallest first**, each a `contrib/` branch (`docs/guides/contributing-upstream.md`):
   1. the canary hit viewer (ready);
   2. the measurement core of the ladder (scoring, isolation, controls, injections, agent suite) on top of the
      agreed matcher, with a short `docs/specs/` version of its spec and the switches off by default;
   3. mitigations as files, the existing defences included (ours, and theirs once agreed in step 2);
   4. experiments and `spe-eval`.
4. **Then the level-free experiments spec** (`BACKLOG.md` *Next*), which should use upstream's catalogue and
   mitigations as merged in steps 1–3, and the study-id answer from collision 2.

**Decisions this needs from the user:** whether to take upstream's study-id exemption (it closes our open
question); the stance on guards that know the canaries; who raises step 2 upstream and when.
