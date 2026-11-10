# The Coder template

Experiments get a Coder template of their own, **`spe-experiments`**, in `platform/coder/experiments-template/`.
The existing template, `spe` (`platform/coder/template/`), is not changed: workspaces from it build and behave as
today, and whether it is kept beside the new one or deleted is decided once the new one has proved itself
(`out-of-scope.md`).

Nothing experiment-specific is written in Terraform: options come from files, the way `spe`'s presets come from
`testbeds/*.yml`.

## What the new template shares and adds

| | `spe` (unchanged) | `spe-experiments` |
|---|---|---|
| Directory | `platform/coder/template/` | `platform/coder/experiments-template/` |
| Presets | `testbeds/*.yml` | one per experiment file, `experiments/*.yml` at the repository root |
| Parameters | samples, tiers, workflows, canaries, flavor, seed, smoke test | the same, plus `experiment` and `mitigations` |
| Build | `run-ansible.sh create.yml` / `destroy.yml` | the same script and playbooks, with `spe_experiments: true` and the experiment's values |
| Apps | Open WebUI, AG-UI chat, Rebuild, Report, Canary hits | the same, plus Evaluations (04) |
| Branch templates | `template/<name>` → `spe-<name>` | `experiment/<name>` → `spe-x-<name>` |

The Ansible side of experiments (the VM-local hand-off, Node and promptfoo on the host, `spe-eval`, `evals-view`,
the extra local vars) is behind `spe_experiments` (default `false`), which only the new template sets, so a build
from `spe` is byte-for-byte today's.

## Where the options come from

The portal pushes one directory per template to Coder (`deploy/sync-template.sh`), and Terraform's `fileset()` sees
only files inside it. The sync assembles the new template's directory before pushing it: it copies
`mitigations/*.yml`, `experiments/*.yml` and `platform/coder/template/run-ansible.sh` into git-ignored places in
`platform/coder/experiments-template/`. It does the same from each `experiment/<name>` branch's worktree for
`spe-x-<name>`, so a branch template's form always matches the code it builds with. Branch names follow the
existing rule (lowercase, digits, hyphens; at most 26 characters, so `spe-x-<name>` stays within Coder's limit).

## Parameters

The existing parameters, as in `spe`, plus:

| Parameter | Type | Options | Default | Mutable |
|---|---|---|---|---|
| `experiment` | string, dropdown | every `experiments/*.yml`, by its file stem, shown by its `name` | `ladder-l0` | yes |
| `mitigations` | list(string), multi-select | every `mitigations/*.yml` without `status: planned`, shown by its `name` | `[]` | yes |

Each experiment file is also a preset: its `parameters` set the form, including `experiment` (its own stem) and
`mitigations` (its `base`: the workspace starts in the baseline arm). `spe-eval` switches arms on the running VM
(03); the form's `mitigations` is the arm the workspace is created in and returns to. Every workspace from this
template has an experiment, so `spe-eval run` always has something to run.

Changing either on a running workspace rebuilds it (stop is destroy, start is create): the form chooses a build,
`spe-eval` compares arms.

## Into Ansible

`local.ansible_vars` is `spe`'s (instance, seed, flavor, samples, tiers, workflows, smoke test, owner, canary
switches), merged in this order with:

1. every selected mitigation's `on` values;
2. the experiment's `vars`;
3. `spe_experiments: true`, `spe_experiment: <stem>` and `spe_mitigations: [ids]`, which `create.yml` records in
   `hardening.json` and in `instances/local.yml`, so `spe-eval` on the VM knows the experiment and the arm it was
   built in.

With `spe_experiments` on, those three, the selected mitigations' values and the experiment's `vars` join
`spe_local_vars` (`group_vars/all.yml`), so `spe-apply` and a Rebuild re-apply the build's arm instead of falling
back to every mitigation off.

Unselected mitigations contribute nothing, so their Ansible defaults (`off`) apply. `create.yml` checks `requires`
and `conflicts` from the mitigation files and refuses a bad combination before creating anything.

## Experiments

The ladder's four (`ladder-l0` … `ladder-l3`, 06) are the first; each contributed experiment adds one file.
