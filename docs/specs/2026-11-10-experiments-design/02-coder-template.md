# The Coder template

One template, `spe` (`platform/coder/template/main.tf`), builds every experiment. Nothing experiment-specific is
written in Terraform: options come from files, the way presets already come from `testbeds/*.yml`. A branch
`template/<name>` gets the same, from its own files, as `spe-<name>`.

## Parameters

Two new parameters, after the existing ones:

| Parameter | Type | Options | Default | Mutable |
|---|---|---|---|---|
| `experiment` | string, dropdown | `none`, plus every testbed with an `experiment:` block, by its file stem, shown by its `name` | `none` | yes |
| `mitigations` | list(string), multi-select | every `mitigations/*.yml` without `status: planned`, shown by its `name` | `[]` | yes |

A testbed sets `experiment` to its own stem in its `parameters`, so picking the preset picks the experiment.
`mitigations` is what the build is made with: for an experiment, its `base` plus, for the mitigated build, its
`mitigation`. An experiment testbed sets `mitigations` to its `base` (the workspace starts in the baseline arm);
`spe-eval` switches arms on the running VM (03), so the form's value is the arm the workspace is created in and
returns to.

Changing either on a running workspace rebuilds it (stop is destroy, start is create): the form is for choosing a
build, `spe-eval` for comparing arms.

## Into Ansible

`local.ansible_vars` (today: instance, seed, flavor, samples, tiers, workflows, smoke test, owner, the canary
switches) is merged, in this order, with:

1. every selected mitigation's `on` values;
2. the experiment testbed's `vars`;
3. `spe_experiment: <stem or "">` and `spe_mitigations: [ids]`, which `create.yml` records in `hardening.json` and in
   `instances/local.yml`, so `spe-eval` on the VM knows the experiment and the arm it was built in.

Unselected mitigations contribute nothing, so their Ansible defaults (`off`) apply. `create.yml` checks `requires`
and `conflicts` from the mitigation files and refuses a bad combination before creating anything.

## Apps

Two `coder_app`s, defined in 04: **Run evaluation** and **Evaluations**. Both are on every workspace; with
`experiment: none`, Run evaluation runs the ladder suite once on the build as it is (no arms).

## Testbeds

`all-data.yml` stays as it is (`experiment` unset: `none`). The ladder adds `ladder-l0.yml` … `ladder-l3.yml` (06).
Each contributed experiment adds one.
