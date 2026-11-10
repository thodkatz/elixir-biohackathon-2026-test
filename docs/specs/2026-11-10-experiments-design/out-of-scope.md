# Out of scope

| Item | Why not now | Where it goes |
|---|---|---|
| A shared, team-wide view of the official ladder results (the replayed evals) on the portal | an experiment's viewer is per workspace and owner-only; a shared one needs its own access rule for canary values and its own service | the backlog item on ladder results for the team, narrowed to that view |
| L4 and L5 as selectable mitigations | L4 (typed tools) is not built; L5 (airlock) is refused while Open WebUI runs | `mitigations/L4.yml`, `L5.yml` stay `status: planned` until their specs land |
| Branch templates from forks or PR refs | the portal makes them from upstream branches only | a later change to `sync-template.sh` |
| CI running `check_experiment.py` | the repositories have no workflows yet | with the first CI workflow |
| A probe for every participant mitigation | a mitigation's `probe` is optional; without one the gate checks only the ladder's | a later spec, if experiments show the need |
| The ladder matrix in the viewer | promptfoo has no levels or conditions | `matrix.py render`, as a command |
| Comparing experiments across workspaces | the seed is secret, so builds differ | the official ladder's controller-side runs |
