# The experiment model

An experiment ties four kinds of thing together. Three are descriptions, one file each, beside each other at the
repository root; the fourth, tests, stays where the suites are. An experiment file names them.

| Kind | Where | Id | Exists today |
|---|---|---|---|
| Threat | `threats/TM-NNN-<slug>.md` | `TM-NNN` | yes (TM-001 … TM-005), checked by `validate.py` |
| Path | `paths/P<n>-<slug>.md` | `P<n>` | no: P1–P4 are a table in the ladder's design text |
| Mitigation | `mitigations/<id>.yml` | `L<n>` for ladder levels, else kebab-case | no: four Ansible variables |
| Test | `platform/promptfoo-evals/tests/<group>.yaml` (ladder) and `tests/experiments/<name>.yaml` | kebab-case `id` in the test's `metadata` | ladder tests yes; experiment tests no |
| Experiment | `experiments/<name>.yml` | the file's stem | no |

**Threat and path differ.** A threat is what goes wrong (data exposure, prompt injection); a path is the concrete
route through this stack (agent-written workflow code, egress). They are many-to-many: TM-001 happens through any
path; TM-003 enters through P1 and usually uses P2. A mitigation closes paths, not threats.

## Paths

`paths/P<n>-<slug>.md`, front matter and body fixed like a threat's (`paths/TEMPLATE.md`):

```markdown
---
id: P2
name: Agent-written workflow code
description: >
  The agent registers a workflow that reads a sensitive file, submits it to WES and reads its output.
reaches: [flag_file, honeypot_files, registry_tokens, vcf_variants]   # canary types, the template's keys
---
# P2: Agent-written workflow code
## Route
## Shown by
```

*Route*: the steps, with the real endpoints. *Shown by*: the probe or test that demonstrates it open. P1–P4 are
written from the ladder's table (06). `reaches` uses the canary types of the Coder template's `canaries`
parameter.

## Mitigations

`mitigations/<id>.yml`:

```yaml
id: L2
name: Data tiers
description: Workflow containers mount only the listed tiers of /data-share and /drs-data.
closes: [P3]                 # path ids; may be empty for a control that narrows rather than closes
on:  {spe_harden_data_tiers: [ref, genomes]}
off: {spe_harden_data_tiers: []}
requires: []                 # optional: mitigation ids that must also be on
conflicts: []                # optional: mitigation ids that must not be on
probe: tier-reach            # optional: the controls-suite probe that shows it, if any
```

- `on` and `off` are the Ansible values; `off` must equal the defaults in `platform/ansible/inventory/group_vars/all.yml`
  (decision 4), so a build without the mitigation is today's build. A value may be a list or a map, which a plain
  boolean switch could not express (L2 is a list).
- A participant's mitigation adds its own variable, default off, named `spe_mitigate_<id with _>`, and guards
  its Ansible change with it.
- `requires` and `conflicts` are checked twice: by `check_experiment.py` on the files, and by `create.yml` on the
  build (as it already refuses the airlock with Open WebUI).
- `hardening.json` (the hand-off) gains `mitigations: [ids]`, the mitigations the build was made with.

## Tests

The ladder's suite (`agent.yaml`, `tests/<group>.yaml`) stays one fixed catalogue run unchanged at every level, so
its levels stay comparable; its count stays pinned by its lint. An experiment's own tests go into
`tests/experiments/<name>.yaml`, same format and labels, run only by that experiment (03). Labels:

| Key | Values | Read from |
|---|---|---|
| `group` | the test files' stems | `tests/*.yaml`, `tests/experiments/*.yaml` |
| `threat` | `TM-NNN` or null | `threats/` |
| `path` | `P<n>` or null | `paths/` |
| `closed_by` | a mitigation id or null | `mitigations/` |

`matrix.CATALOGUE` is built from these files at import (decision 3); its role as the one definition the lint and
`counts` share does not change, and the ladder's ids (TM-001…, P1–P4, L1–L5) keep their meaning, so committed
counts stay valid. L4 and L5 stay valid `closed_by` values while their mitigation files do not yet exist: a
mitigation may be listed with `status: planned` and no `on`/`off`, which the form does not offer.

## Experiments

An experiment file is a preset of the `spe-experiments` template (02), in the shape of `spe`'s testbeds, with an
`experiment:` block and, optionally, `vars:`:

```yaml
name: TRS guard
description: Does validating TRS writes stop agent-written workflows?
parameters:              # the template's parameters; `experiment` and `mitigations` as well
  experiment: trs-guard
  mitigations: []        # = base: the workspace starts in the baseline arm
  samples: [HG002, HG003, HG004, HG005]
  ...
experiment:
  threat: TM-003
  paths: [P2]
  mitigation: trs-guard  # the one under test: off in the baseline arm, on in the mitigated arm
  base: []               # mitigations on in both arms
  tests: [register-broken-workflow, summarise-workflows]   # ids; the utility group always runs as well
vars:                    # Ansible values the experiment needs that are not form parameters
  spe_frontends: [agui]
  spe_eval_sink: true
```

`vars` exists because a preset can only set form parameters, and an evaluation needs build settings the form does
not offer (frontends, the test receiver, injections). `main.tf` applies them (02). Keys in `vars` that a mitigation
or a parameter also sets are refused by the checker: one place per value.

An experiment fixes no seed: the seed is secret (it reproduces every canary), and the two arms already
share one build's canaries. Comparison across workspaces is the official ladder's business, not an experiment's.
