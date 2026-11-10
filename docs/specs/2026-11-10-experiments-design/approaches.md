# Approaches

## Where an experiment is measured

| | How | Trade-off | |
|---|---|---|---|
| **A. One workspace, arms switched on the VM** | `spe-eval` applies the baseline arm, runs, applies the mitigated arm, runs; both on the workspace's VM from its clone | one VM, one build, the same canaries: the two arms differ only in the mitigation. A run takes twice one arm. The hand-off sits on the VM (03 says why that is acceptable here) | **chosen** (the agent's call in the design conversation of 2026-11-10; the user went on from it without objecting) |
| B. Two workspaces | a baseline testbed and a mitigated one, compared across | two VMs, and two builds whose canaries differ unless the seed is fixed, and the seed is secret; breaks one-instance-at-a-time quotas | rejected |
| C. Run from the portal VM | a portal service runs `run.sh` against the workspace's controller hand-off; a Coder link triggers it | the answer key never reaches the VM, as for the official ladder; but the portal's checkout is upstream `main`, so a participant's uncommitted mitigation and tests are not in the run | rejected for experiments; it is the official ladder's route, which stays |

## How results are shown

| | Trade-off | |
|---|---|---|
| **`promptfoo view` on the VM behind a Coder app** | promptfoo's own UI: results table, outputs, tool calls, side-by-side evals; a normal `coder_app`, owner-only; its run endpoints must be blocked | **chosen** |
| A results page of our own in the report service | full control, the ladder matrix possible; a second UI to build and keep | not now; the matrix stays a command (04) |
| `promptfoo view`'s own Run button as the trigger | no `spe-eval` to build; but it runs a bare suite: no checks, no controls gate, no lock, no arms | rejected (04, *Read-only*) |

## How options grow

| | Trade-off | |
|---|---|---|
| **Options read from files** (`fileset()` over testbeds, as presets already are, and over `mitigations/`, which the sync copies into the pushed template directory) | a contribution adds files, never Terraform | **chosen** |
| One `coder_parameter` per mitigation | explicit, but every contribution edits `main.tf` | rejected |
| A `level` parameter L0–L3 | simple for the ladder; no place for a participant's mitigation, and a level bundles controls a participant cannot pick apart | rejected: levels become testbeds |

## Existing tools searched

Needs, in the user's terms: a participant proposes a mitigation, measures it against the agent on a real SPE build,
sees the results, and contributes it so others can rebuild and remeasure it.

- **promptfoo** (in use): its viewer is taken whole; its eval creator is not used as a trigger (above).
- **Coder presets and parameters** (in use): taken; the form is how a build is chosen.
- **AgentDojo** (prompt-injection benchmark with pluggable attacks and defenses) and **Inspect** (UK AISI's eval
  framework, with its own log viewer): both would replace promptfoo and model the environment as tools in Python;
  here the target is a deployed stack with real APIs, canaries and controls at the infrastructure layer, and the
  suites, scoring and isolation already exist on promptfoo. Taking either whole would leave the stack, the
  switches, the reset and the canaries to write again around it. Not used. Not trialled; recorded from what each
  is known to do, as of this spec.
