# Inputs for the plan

## Slices, in order

| # | Slice | Decisions | Needs an instance |
|---|---|---|---|
| 1 | **The catalogue as files**: `paths/` (P1–P4, template), `mitigations/` (L1–L3, L4–L5 planned), `validate.py` over all three, `matrix.CATALOGUE` read from files, `tests/experiments/` | 2, 3, 4 | no |
| 2 | **The form**: `experiment` and `mitigations` parameters, the merge into `ansible_vars`, `requires`/`conflicts` in `create.yml`, `hardening.json` `mitigations`, ladder testbeds | 1, 5, 6 | one de.NBI build (`ladder-l2`) |
| 3 | **`spe-eval`**: VM-local hand-off, local `isolation`, per-arm snapshots, the two arms, `run.sh`'s suite argument and gate for mitigations, lock, archive | 7–11, 13 | de.NBI, a `--repeat 1` run |
| 4 | **The viewer and apps**: `evals-view`, the read-only proxy, Run evaluation, Evaluations; the early output | 14–16 | de.NBI |
| 5 | **Eval runs apart in canary hits**: provider mark, run-log `source`, the watcher and pages | 12 | de.NBI |
| 6 | **Contribution**: `check_experiment.py`, PR template, `CONTRIBUTING.md`, the workspace guide's section; a worked example experiment beyond the ladder (e.g. a TRS guard) built with it | 17 | de.NBI |

Slices 3 and 4 together give the early output (README).

## Dependencies

- **The ladder upstream.** `run.sh`, `isolation.py`, `matrix.py`, the probes and the `spe_harden_*` switches are on
  the fork only, not yet upstream; the canary hit viewer likewise. The portal follows upstream, so nothing here
  reaches participants until those are ported. Slices can be built and checked on the fork and a de.NBI instance
  first; their upstream port follows the ladder's.
- **Branch templates from upstream only.** Step 5 of the contribution path needs push access to upstream; making
  branch templates from forks or PR refs is out of scope (`out-of-scope.md`).

## For the plan to settle

- The writes `promptfoo view` 0.125.1's reading UI needs (04, *Read-only*), from its routes, with a test.
- How the generated experiment suite config is built (a file `spe-eval` writes, or `agent.yaml` filtered by
  promptfoo's `--filter-pattern`/metadata filter) and that the utility group runs in it.
- Whether `spe-apply all` is the narrowest apply that switches every ladder mitigation (L3's compose overlay is
  written by the frontend roles) or a tag set suffices.
- The progress line source (the `afterEach` hook appending to a file `spe-eval` tails).
