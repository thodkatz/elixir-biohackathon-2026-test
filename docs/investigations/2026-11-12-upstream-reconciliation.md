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

## Where the fork fits: red, blue, judge

Worked out with the user after the comparison (same session). The frame is test-driven: an attack becomes a test
that fails, a mitigation makes it pass, and the suite is the regression check. **The tests are the reference
point**, and the goal is a suite that passes with every mitigation on.

| Role | Who | What |
|---|---|---|
| **Red**: find attacks | Josef's threatlab (upstream, unmerged) | generates attacks with mitigations off, confirms a hit by replaying it unchanged |
| **Blue**: propose mitigations | a person today; an agent possibly later; **nobody has built this** | a new mitigation (an Ansible switch) for the tests a new threat turned red |
| **Judge**: accept a mitigation | **the fork** | decides whether a mitigation really closes the gap without breaking the service |

**The acceptance rule** the judge applies: the tests the mitigation targets go green; no utility test goes red; the
mitigation's controls probes confirm it is on; the pass holds over repeats against a threshold; and it is evaluated
against canaries it was not given.

**Why "pass the tests" needs a judge.** Each clause of the rule stops one way to turn the suite green without making
anything safer:

| Cheat | Stopped by |
|---|---|
| Break the agent (cut its network, remove its tools) | utility tests in the suite |
| Know the answer key (match the planted canary list) | canaries the mitigation never sees (spec decision 12; Yasin's guard, collision 1) |
| The switch silently does not apply; green comes from the model | the controls gate |
| One lucky run | repeats and a pass threshold |
| One test contaminating the next | isolation |

**Where a baseline is still needed**: not per experiment, but in three places:
1. **Red first, once per test, when it is added**: a test that passes with every mitigation on may only show that
   the attack never fired. A promoted threatlab attack carries this from its replay.
2. **One mitigation off**: with every mitigation on, a green suite can't say which mitigation closes which test. One
   off per arm fills `closes` and shows redundancy (the core of the close-the-loop item in `BACKLOG.md`).
3. **Red again after the model changes**: tests are rates (4/5), not booleans, and a new model may turn a test green
   by itself.

**Two limits of the frame.** A new threat does not always need a new mitigation: its tests may already pass, which is
evidence of coverage. And some gaps can't be closed by a switch: the ladder results show the infrastructure
mitigations do not stop leaks through the answer (`docs/results/canary-ladder-qwen3.8-27b.md`).

**What the fork really has, in this frame.**
- The judge: the mitigation format (switches, probes, `closes`), the controls gate, isolation, canary metrics,
  planted injections and the test receiver, and the runner that applies one set of mitigations and runs the suite.
- Four working mitigations and their measured results.
- The catalogue extensions: paths, mitigations and experiments next to upstream's threats. The threat template,
  vocabulary and threat validator are upstream's; the fork changed 4 lines of `threats/TEMPLATE.md`.

**What loses its role:** the hand-written experiment layer: `experiments/*.yml`, `check_experiment.py`, and the
per-experiment contribution flow (the spe-experiments form, `CONTRIBUTING.md`, `spe-eval pr-body`). It was built
for a person proposing one experiment at a time. In the loop, the test (labelled `threat`, `path`, `closed_by`) is
the experiment, and the matrix is every test × every mitigation. A participant contributes a mitigation (blue) or
runs the loop (red).

**What the loop needs at the join.**
- **Freeze before measuring:** a confirmed attack becomes a committed test with a hash before it is measured. If the
  loop generated attacks in each arm, the arms would differ in the attack, not only in the mitigation. This meets
  Josef's `354c8c9` (scenarios off git). A possible compromise: the scratch work stays local, and promoted attacks are
  committed.
- **Scoring on canaries:** a promoted attack is rewritten to aim at a canary file, as the planted injections do; his
  `{nonce}` indicators say *that* it worked, canaries say *what* leaked and where.
- **Optional, and costly:** re-running the search against the mitigated build asks whether a mitigation holds against
  an attacker that adapts. That is a different question from the judge's.

The pitch upstream: *Josef's loop finds attacks, a person (later perhaps an agent) proposes mitigations, and our
harness judges whether a mitigation closes the gap without breaking the service.* A blue agent only becomes safe to
allow once there is a strict judge.

## The baseline and the mitigation's granularity

Two follow-up questions from the user, answered in the same session.

**The baseline is the previous commit.** In the test-driven frame a mitigation is a feature: a new threat lands as
failing tests, a mitigation PR turns them green, and the next threat starts the cycle again. "Baseline" then means
nothing more than the suite on `main` before the mitigation's PR, as CI shows any feature's tests failing before
and passing after. It needs no arm of its own. What differs from ordinary software: tests are rates over repeats,
not booleans; a model change is a dependency upgrade, so the whole suite reruns; and "which mitigation closes this
test" is asked by switching one off, the way a feature flag is turned off to see what depends on it.

**A mitigation is one control at one enforcement point, not one threat or one Ansible role.** The current split
follows the paths (the system's boundaries), not the threats: `trs-read-only` closes P2 at the TRS and WES APIs,
`data-tiers` P3 at the workflow mounts, `egress-allowlist` P4 at the network, the airlock the answer. A threat
crosses several paths (TM-001 needs all four closed) and a mitigation serves several threats, so the threat can't
be the unit. Nor can the role: `trs-read-only` is one switch (`spe_harden_trs_readonly`) touching Traefik and WES
config in `workflow_stack`, and a mitigation with a large Ansible setup is still one mitigation. The test of the
unit is the controls probe: one mitigation is a control a model-free probe can show to be on or off
(`probes: [trs-write, wes-inline, e2e-exploit]`), independently of the others.

**Why not one config.** For a deployment it is one config: everything on is the product. The split is kept because:
1. **Attribution:** one off at a time says what each control buys; one config can only be all on or all off.
2. **Cost:** each control can break legitimate work (utility tests), and SPEs differ in what they can adopt (a site
   may not run an egress allowlist), so a deployer needs to drop one and know what reopens.
3. **Review:** one mitigation per PR, as one feature per PR.
The switches cost combinations and conflicts (`trs-guard` against `trs-read-only`). A possible rule, for the
close-the-loop spec: a mitigation stays a switch while it has a utility cost or a site may decline it; one with
neither could graduate into the base config, as a feature flag is removed once the feature is settled.

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
   4. the judge's runner (`spe-eval`'s arm runner, without the hand-written experiment layer, see *Where the fork
      fits*).
4. **Then the "close the loop" spec** (`BACKLOG.md` *Next*; it replaces the level-free experiments spec and keeps
   its core): every mitigation on as the reference, one off per arm, utility labels, repeats, the acceptance rule,
   the freeze step at the join with threatlab, and what to retire from the experiments track. It should use
   upstream's catalogue and mitigations as merged in steps 1–3, and the study-id answer from collision 2.
5. **Record the direction** as a `biohackathon` knowledge record once the user has talked to Josef and Kraatz, with
   this investigation as its evidence.

**Decisions this needs from the user:** whether to take upstream's study-id exemption (it closes our open
question); the stance on guards that know the canaries; who raises step 2 upstream and when; whether Kraatz sees
threatlab as upstream's direction.
