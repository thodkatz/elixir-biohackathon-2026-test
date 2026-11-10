# Evaluation in the workspace

An experiment is measured on the workspace's own VM, by a new command `spe-eval`
(`platform/instance/spe-eval`, installed next to `spe-apply`), from the clone in `~/sperange`. That is where the
participant's mitigation and tests are, committed or not; a run from the portal's checkout would not see them.

The route a maintainer uses today, `run.sh` from the controller against the hand-off in
`platform/ansible/output/<instance>/`, stays as it is for official ladder runs: there the hand-off never reaches
the machine under test.

## The hand-off on the VM

`create.yml` writes a second copy of the hand-off into `~/spe-eval/handoff/` on the VM (mode 0700, owned by the
workspace user): `canaries.json`, `hardening.json`, `injections.json`, `agent_api_key`, and a `hosts.yml` without an
SSH prefix, so `isolation.vm_runner` runs commands locally (the path it already has for an empty prefix). Plus the
LLM key file the key-leak metric reads. None of it is mounted into any container.

This puts the answer key on the machine under test. That is acceptable here because the workspace already holds the
seed, from which every canary follows (`platform/ansible/instances/local.yml`, written for `spe-apply`); the agent
reaches neither, since both sit outside every container's mounts (decision 8's check covers both paths; the
viewer's mount, `~/spe-eval/promptfoo`, holds results, not the hand-off).

Node and promptfoo (the version `platform/promptfoo-evals/package.json` pins) are installed on the VM host, for the
workspace user, by the role that writes the hand-off: promptfoo's hooks drive Docker and read the hand-off, so in a
container it would need the Docker socket and the hand-off mounted, which decision 8 rules out.

## `spe-eval`

```
spe-eval run [--repeat N]                  both arms of the workspace's experiment; refuses without one
spe-eval arm baseline|mitigated            apply one arm (spe-apply all with its mitigation values), no run
spe-eval status                            the lock, the current arm, the last run's result lines
```

`run`, for an experiment:

1. **Lock** `~/spe-eval/lock`; refuse if held. `spe-apply` refuses while it is held (decision 11).
2. **Baseline arm.** `spe-apply all` with extra `-e` values (`spe-apply` today passes extra arguments only in its
   `ansible` form; `all` and `stack` learn to pass them too) with the base mitigations' `on` and the mitigation under test's `off`;
   rewrite the VM hand-off's `hardening.json` for this arm; wait until the stack answers.
3. **Run** `run.sh` with reports in `reports/<experiment>/<arm>/` (its checks, the controls suite and its gate, then the agent suite) with the experiment's
   tests plus the utility group, `--repeat N --no-cache`, `PROMPTFOO_CONFIG_DIR=~/spe-eval/promptfoo` (the viewer's
   database), and an eval description `<experiment> baseline [<mitigation ids>] <model>`.
4. **Mitigated arm.** The same with the mitigation under test `on`; run again, described `… mitigated …`.
5. **Return** to the arm the workspace was built with (its `spe_mitigations`), release the lock, print where the
   results are: the Evaluations app.

`repeat` defaults to 1 for an experiment (a participant's iteration); the ladder's 3 or 5 is a flag away. The run
uses whatever model the workspace's agent is configured with, paid or not; `spe-eval` puts no guard on the provider.

**An arm is its mitigation set, not a level.** `run.sh` today names a run by `hardening.json`'s level, and
`handoff.check_hardening` requires that level to count the ladder switches from L1 without a gap. Both stay true for
the ladder: the level is still derived from the ladder mitigations that are on, and `check_experiment.py` refuses
an experiment whose ladder mitigations (base plus the one under test) are not contiguous from L1. A participant's
mitigation adds no level, so both arms of `trs-guard` are level 0; what tells them apart is the arm, in the
reports directory, `run.json` (`experiment`, `arm`, `mitigations`) and the eval description. The ladder's
controller-side runs keep `reports/L<n>/` and the matrix as they are.

`run.sh` gains a suite argument (the ladder's `agent.yaml`, or a generated config with the experiment's tests and
the utility group), and the gate learns participant mitigations: a mitigation with a `probe` adds that probe's
expectation; one without adds none.

## Snapshots per arm

`isolation.py` keys a snapshot to the build's canaries. Both arms share those canaries, but a mitigation may change
what the volumes hold (a registration, a description), so restoring the baseline's snapshot into the mitigated arm
would undo it. The snapshot key becomes canaries plus the arm's mitigation set (decision 9); each arm snapshots on
its first run and restores from its own. Today a snapshot replaces the instance's whole snapshot directory
(`SNAP_SH`'s `rm -rf`), and the dirty-stack marker records only the canaries' `generated_at`: both change, so a
snapshot replaces only its own key's directory and the marker records the key, mitigation set included.

## While a run is going

A run takes the workspace over: every test restores the stack, so the chat is not usable meanwhile and its answers
would be reset. The Run evaluation app says so before it starts and prints a progress line per test (from the
`afterEach` hook). The restore leaves chats, the agent's run log and Open WebUI's data alone, as it does today; what
a participant registered by hand in TRS or WES is reset to the snapshot, which is taken on an arm's first run.

## Canary hits

The promptfoo provider marks each run it starts (AG-UI `forwardedProps`), and the agent writes `source: eval` on
that run's log line. Test-receiver requests carry no run, so `spe-eval` records each run's window (start and end
time) in `~/spe-eval/windows.jsonl`, and the watcher's reader returns it: a receiver hit inside a window is an eval
hit. The canary hit watcher keeps the source with each hit, and the hits pages show eval hits under
their own heading, out of the counts of chat hits (decision 12): at L0 a suite leaks on purpose, and those hits
would otherwise bury the participant's own.

## Archive

On stop, `archive.yml` copies `~/spe-eval/reports/` (each arm's `controls.json`, `agent.json`, `hardening.json`,
`run.json`) and `~/spe-eval/promptfoo/` into the run directory's `evals/` (decision 13). They hold canaries, as the
run directory's chats and `canaries.json` already do.
