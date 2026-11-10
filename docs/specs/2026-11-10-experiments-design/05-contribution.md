# Contributing an experiment

## The path

1. **A workspace from `spe`**, with any testbed (or an existing experiment to build on).
2. **Build the experiment**, usually by asking the workspace's coding agent (Coder Agents, which follows
   `platform/instance/workspace/AGENTS.md`), or by hand:
   - the threat (`threats/`, from `TEMPLATE.md`) and the path (`paths/`), if new;
   - the mitigation: its Ansible change guarded by `spe_mitigate_<id>` (default off), and `mitigations/<id>.yml`;
   - its tests, `tests/experiments/<name>.yaml`;
   - the testbed, `testbeds/<name>.yml`, with its `experiment:` block and `parameters.experiment: <name>`.
3. **Try it live**: `spe-eval arm mitigated` to apply it, chat with the agent; then **Run evaluation** and
   **Evaluations** for the two arms.
4. **Check**: `python3 check_experiment.py <name>`.
5. **Build it fresh** (when the change acts only at creation, or to confirm a clean build): push
   `template/<name>`; the portal makes `spe-<name>`, whose form already offers the new mitigation and experiment.
6. **Open a PR** from the branch, with the experiment PR template. Merged upstream, the experiment and its
   mitigation appear on `spe`'s form for everyone within minutes.

The portal follows upstream's `main` and makes branch templates from upstream branches, so step 5 needs push
access there and step 6 is an upstream PR.

## `check_experiment.py <name>`

At the repository root, beside `validate.py`, standard library plus PyYAML, offline, under a minute. It checks the
experiment's structure, not its result:

- the testbed exists, has an `experiment:` block, and sets `parameters.experiment` to its own stem;
- its threat, paths, mitigation, base mitigations and test ids resolve to files and tests;
- `validate.py` passes (threats, paths, mitigations);
- each named mitigation's `off` equals the Ansible defaults; `requires` and `conflicts` hold for base plus the one
  under test;
- each test's labels resolve (the catalogue lint) and its Python assertions name real functions;
- the testbed's `parameters` keys are parameters of `main.tf`, and its `vars` set no key a mitigation sets.

Each refusal names the file and the id. Its unit tests cover one refusal each.

It is the gate of a contribution: the coding agent runs it as the last step, the participant pastes its output into
the PR, a reviewer runs it on the branch, and CI runs it once the repository has workflows. Whether the mitigation
*works* is the result's job, below.

## The PR

`.github/PULL_REQUEST_TEMPLATE/experiment.md`, chosen with `?template=experiment.md` on the new-PR link the
workspace guide gives:

```markdown
## Experiment: <name>

**Threat:** TM-NNN (new / existing): <one line>
**Paths:** P<n> (new / existing): <the route>
**Mitigation:** `<id>` (`spe_mitigate_<id>`): <what it changes, where>
**Testbed:** `platform/coder/template/testbeds/<name>.yml`

### Files
- [ ] threat and path files, if new (`validate.py` passes)
- [ ] `mitigations/<id>.yml`; the Ansible change behind `spe_mitigate_<id>`, default off
- [ ] `platform/promptfoo-evals/tests/experiments/<name>.yaml`
- [ ] the testbed, with its `experiment:` block

### Result
Model: <provider / model>   Repeat: <n>
<`matrix.py counts` of each arm, or the rendered table: baseline vs mitigated>
Utility tests pass with the mitigation on: yes / no

### Checks
`python3 check_experiment.py <name>`: <output>
```

The result is `matrix.py counts` output: labels and counts only, never an answer or a token, so it can be posted.
A reviewer who wants to see it reproduced creates a workspace from `spe-<name>` and presses Run evaluation.

## The guides

- `CONTRIBUTING.md` (new, root): how to contribute an experiment, for people; points to the PR template and the
  checker.
- `platform/instance/workspace/AGENTS.md`, a new section *Contributing an experiment*: the same steps for the
  coding agent, including that a mitigation is a switch with a default of off, and that it runs the checker and
  reports its output before pushing.
- `threats/TEMPLATE.md`'s *Detective* section points to experiments for the promptfoo side.
