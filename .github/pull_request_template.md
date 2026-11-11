## Experiment: <name>

**Threat:** TM-NNN (new / existing): <one line>
**Paths:** P<n> (new / existing): <the route>
**Attack:** <a prompt test, or injection `<id>` (new / existing): its surface and action> (if any)
**Mitigation:** `<id>` (`spe_mitigate_<id>`): <what it changes, where> (if any)
**Base:** <base mitigations: the build it runs on>
**Experiment file:** `experiments/<name>.yml`

### Idea and rationale
<why this attack or mitigation, what was tried, known limits>

### Result
Model: <provider / model>   Repeat: <n>
<`matrix.py counts` of each arm, or the rendered table: baseline vs mitigated>
Utility tests pass with the mitigation on: yes / no (if a mitigation)

### Checks
`python3 check_experiment.py <name>`: <output>

<!-- Not an experiment PR? Delete the text above and say instead what this PR changes, why, and
     how it was checked (tests run, commands used). -->
