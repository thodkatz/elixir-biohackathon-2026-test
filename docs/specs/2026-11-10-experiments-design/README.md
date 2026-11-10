# Experiments: threat, mitigation, tests and results, end to end in a workspace

Status: draft (fork PR #84). Latest clarification: none.

**Who reads it.** Whoever plans or builds the slices; reviewers of an experiment PR; maintainers of the Coder
template (`platform/coder/`), the evaluations (`platform/promptfoo-evals/`) and the instance (`platform/instance/`).

**The problem.** The parts of an evaluation exist, but only a maintainer can put them together, by hand, from
their own controller. A threat is a file in `threats/`; the routes a canary takes (paths P1–P4) and the controls
that close them (the `spe_harden_*` switches) live only in a design text and in Ansible variables; the test labels
are a fixed set in `matrix.py`; `run.sh` runs only where the instance's hand-off is (the controller); results are
read with `promptfoo view` on a laptop. A participant in a portal workspace can change the stack (`spe-apply`) and
chat with the agent, but cannot pick a hardened build, run the suite, see its results, or contribute a mitigation
that others can rebuild and measure.

**The decision.** An **experiment** is a testbed file (a Coder preset) plus the files it names: a threat, the
paths it takes, a mitigation written as a switch, and tests. The Coder template reads mitigations and experiments
from files, so contributing one adds options without editing Terraform. In the workspace, `spe-eval run` measures
the experiment on the workspace's own VM: the suite with the mitigation off (baseline), then on (mitigated), same
build and canaries; a read-only `promptfoo view` behind an "Evaluations" app shows both. A contribution is a PR
of those files, gated by `check_experiment.py` and carrying its result. The canary ladder is the first set of
experiments, built through exactly this structure.

## Decisions taken

| # | Decision | Part | Acceptance check |
|---|---|---|---|
| 1 | An experiment is a testbed file with an `experiment:` block naming one threat, its paths, the mitigation under test, the base mitigations and its tests; the code it names lives in the repo | [01](01-experiment-model.md) | `check_experiment.py ladder-l1` passes; a testbed naming an unknown threat, path, mitigation or test id fails it with that id in the message |
| 2 | Paths and mitigations are files like threats: `paths/P<n>-<slug>.md`, `mitigations/<id>.yml`; `validate.py` checks all three | [01](01-experiment-model.md) | `validate.py` passes on P1–P4 and L1–L3; a path without its front matter keys, or a mitigation whose `off` differs from the Ansible default, fails it |
| 3 | The test labels' value sets are read from those files, not listed in code: `threat` from `threats/`, `path` from `paths/`, `closed_by` from `mitigations/`; `group` from the test files' names | [01](01-experiment-model.md) | `tests/test_catalogue.py` passes with `matrix.CATALOGUE` built from the files; adding `paths/P5-x.md` makes `path: P5` valid with no code change; `matrix.py counts` on the committed ladder results is unchanged |
| 4 | A mitigation declares its Ansible values when on and when off; off is the default, so a build without it is today's | [01](01-experiment-model.md) | `check_experiment.py` refuses a mitigation whose `off` values differ from `group_vars/all.yml`; a workspace with no mitigation selected builds the same `ansible_vars` as today (a Terraform plan diff of zero for those keys) |
| 5 | The ladder's levels become mitigations `L1`, `L2`, `L3` (ids kept, so `closed_by: L1` stays valid) and experiments `ladder-l0` … `ladder-l3` (base: the lower levels; under test: that level) | [06](06-ladder-as-example.md) | a workspace from `ladder-l2` builds with `hardening.json` at level 2; `spe-eval run` there gives a baseline eval at level 1 and a mitigated one at level 2 |
| 6 | The Coder form gets a **Mitigations** multi-select (one option per `mitigations/*.yml`) and an **Experiment** select (one per testbed with an `experiment:` block, plus "none"); `main.tf` merges the selected mitigations' `on` values and the experiment's `vars` into `ansible_vars` | [02](02-coder-template.md) | Terraform test: experiment `ladder-l2` yields `spe_harden_trs_readonly: true`, `spe_harden_data_tiers: [ref, genomes]`, `spe_frontends: [agui]`; a new `mitigations/x.yml` appears as an option after the template push with no `main.tf` change |
| 7 | Evaluations of an experiment run on the workspace VM, from the clone in `~/sperange`, by `spe-eval`; the controller-side `run.sh` route stays for official ladder runs | [03](03-evaluation-in-workspace.md) | in a workspace, a test added only in the clone (uncommitted) is part of `spe-eval run`'s eval |
| 8 | Create writes a VM-local hand-off into `~/spe-eval/handoff/` (mode 0700, the workspace user), mounted into no container, with an SSH-less `hosts.yml` so `isolation.py` and the probes run locally | [03](03-evaluation-in-workspace.md) | `isolation.py exists/snapshot/restore` work on the VM with no SSH; `docker inspect` of every container on the VM shows no mount containing `spe-eval` |
| 9 | `spe-eval run` measures two arms: base mitigations only (baseline), then base plus the mitigation under test (mitigated), each applied with `spe-apply all` and each with its own isolation snapshot | [03](03-evaluation-in-workspace.md) | the snapshot key includes the arm's mitigation set (an isolation test); after a run, the stack is left in the arm the workspace was built with |
| 10 | Each arm runs the controls suite and gate, then the experiment's tests plus the utility group, `--no-cache`; an eval's description names experiment, arm, mitigation set and model | [03](03-evaluation-in-workspace.md) | promptfoo's eval list after a run holds `<experiment> baseline` and `<experiment> mitigated`, each with controls and agent evals |
| 11 | `spe-eval` refuses the agent suite on a paid provider (`spe_agent_model_provider: anthropic`) unless `--allow-paid`; one run at a time per VM (a lock), and `spe-apply` refuses while it is held | [03](03-evaluation-in-workspace.md) | unit tests of `spe-eval`: anthropic without the flag exits non-zero before any promptfoo call; a second `spe-eval run` and `spe-apply` both refuse while the lock is held |
| 12 | Runs started by an evaluation are marked in the agent's run log, and the canary hits pages show their hits apart from the participant's own | [03](03-evaluation-in-workspace.md) | a run log line from the promptfoo provider carries `source: eval`; the hits page test shows eval hits under their own heading, not in the counts of chat hits |
| 13 | On stop, the archive copies `~/spe-eval/reports/` and the promptfoo database into the run directory | [03](03-evaluation-in-workspace.md) | `archive.yml` test: the run directory holds `evals/` with each arm's reports |
| 14 | The viewer is `promptfoo view` 0.125.1 as compose service `evals-view` on the VM, on `127.0.0.1` and its own network, reading `~/spe-eval/promptfoo`; evals are written there directly by `spe-eval` | [04](04-viewer.md) | from the sandbox, a request to the host on the viewer's port fails; from the VM, `curl 127.0.0.1:<port>/api/results` lists the evals |
| 15 | The viewer is read-only: a proxy in front of it refuses every endpoint that starts, replays or changes an eval, and it holds no provider or agent key | [04](04-viewer.md) | `POST /api/eval/job` and `POST /api/eval/replay` through the proxy return 403; the container's environment has no `*_KEY` variable |
| 16 | Two Coder apps on every workspace: **Run evaluation** (a terminal running `spe-eval run`, ending in a shell) and **Evaluations** (the viewer, `share = "owner"`) | [04](04-viewer.md) | both apps appear on a workspace from `spe`; Evaluations is refused to another logged-in user |
| 17 | A contribution is one PR of the experiment's files, with its result; `check_experiment.py <name>` is its gate; a PR template and `CONTRIBUTING.md` say what is expected, and the workspace guide teaches the coding agent the same steps | [05](05-contribution.md) | `check_experiment.py` runs offline in under a minute and its unit tests cover each refusal; the PR template's checklist names exactly what the checker checks |

**Early output.** One workspace on de.NBI from `ladder-l1`, one `spe-eval run --repeat 1`, and the Evaluations
app showing the baseline (L0) and mitigated (L1) evals side by side. The user looks at it: whether the two arms
read as one comparison in promptfoo's UI, and whether the run from the button is a flow a participant could follow
alone. What would change a decision: an unreadable comparison changes 10 and 14 (eval naming, or a summary page of
our own); a run too long or confusing for a participant changes 9 and 16 (fewer tests per arm, a progress line).
It needs slices 1–4 (*Inputs for the plan*); slice 2's create form is the smaller sample before it.

## Glossary

| Term | Meaning |
|---|---|
| **Threat** | A class of harm, `threats/TM-NNN-*.md` |
| **Path** | A route by which a canary reaches the agent or leaves the SPE, `paths/P<n>-*.md` |
| **Mitigation** | A control that closes or narrows paths, written as Ansible values when on and off, `mitigations/<id>.yml` |
| **Experiment** | A testbed with an `experiment:` block: one threat, its paths, one mitigation under test, base mitigations, tests |
| **Testbed** | A Coder preset, `platform/coder/template/testbeds/<name>.yml` |
| **Arm** | One of an experiment's two builds: **baseline** (base mitigations) or **mitigated** (base plus the one under test) |
| **Hand-off** | The instance's files the evaluations read: `canaries.json`, `hardening.json`, `injections.json`, `hosts.yml`, `agent_api_key` |
| **Ladder** | The experiments `ladder-l0` … `ladder-l3`, each adding one level's mitigation |

## Parts

| File | What | Read when |
|---|---|---|
| [01-experiment-model.md](01-experiment-model.md) | the files: threats, paths, mitigations, tests, testbeds; the catalogue read from them | you add or check any of those files |
| [02-coder-template.md](02-coder-template.md) | the form's parameters, how they become Ansible values | you change `main.tf` or a testbed |
| [03-evaluation-in-workspace.md](03-evaluation-in-workspace.md) | `spe-eval`: hand-off on the VM, the two arms, guards, canary hits, archive | you build or change the run |
| [04-viewer.md](04-viewer.md) | the viewer service, its read-only proxy, the two apps | you build or change the viewer |
| [05-contribution.md](05-contribution.md) | a participant's path to a PR; the checker, PR template, guides | you build the contribution path or review an experiment PR |
| [06-ladder-as-example.md](06-ladder-as-example.md) | the ladder expressed as experiments | you build slice 1–2, or explain the structure |
| [approaches.md](approaches.md) | what was considered and why this way; existing tools searched | you question the design |
| [inputs-for-plan.md](inputs-for-plan.md) | slices, order, dependencies | you write the plan |
| [out-of-scope.md](out-of-scope.md) | what this spec leaves out, and where it went | you look for something not here |
| [clarifications.md](clarifications.md) | the decision log | the design changed after approval |
