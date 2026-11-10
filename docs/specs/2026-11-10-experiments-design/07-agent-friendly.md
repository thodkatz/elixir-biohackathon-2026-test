# Built for coding agents

Most participants will run the whole path through a coding agent: Coder Agents in the dashboard, or Claude Code,
Codex or opencode in the workspace terminal. (This is the participant's helper, not the SPE agent under test.) So
every step a person does with a button, an agent can do with a command, read back as text, and judge from its
exit code. The buttons (Run evaluation, Evaluations) are views over the same commands, never the only way.

## One entry point for the agent

`platform/instance/workspace/AGENTS.md`, which every one of those agents reads in the workspace, gets a section
*Experiments*: the path of 05 as numbered steps, each with its command and what success prints. It points to
`experiments/README.md`, the index of experiments (one line each: name, threat, paths, mitigation), and to the
ladder experiments as worked examples. Nothing an agent needs is only in a UI or only in this spec.

## Commands

| Step | Command | For an agent |
|---|---|---|
| Start | `spe-eval new <name> [--threat TM-NNN] [--path P<n>] [--from <experiment>]` | writes the skeleton: `experiments/<name>.yml`, `mitigations/<name>.yml` with a `spe_mitigate_<name>` switch, its default in `group_vars`, `tests/experiments/<name>.yaml` with one labelled test, and threat or path files from their templates when the ids are new; prints each path and the `TODO`s to fill |
| Check | `check_experiment.py <name> [--json]` | each problem as `file:line: id: what is wrong: what to do`; `--json` the same as a list |
| Try | `spe-eval arm baseline\|mitigated` | applies one arm and exits when the stack answers |
| Run | `spe-eval run [--repeat N] [--detach]` | `--detach` starts the run in the background (a user systemd unit) and returns at once with its id; the agent's own command timeouts never cut a run short |
| Watch | `spe-eval status [--json]` | the lock, arm, test *k* of *n*, last error; `spe-eval wait [--timeout S]` blocks until the run ends or the timeout passes, for agents that can wait in bounded steps |
| Read | `spe-eval results [--json] [--test <id>]` | the two arms side by side as text: per test and metric, baseline and mitigated pass counts, the utility tests' outcome, and a one-line verdict per metric (closed, narrowed, unchanged, worse); `--test` adds that test's assertion reasons |
| Share | `spe-eval pr-body <name>` | prints the PR template filled in: the files, the counts, the checker's output, ready to paste or pass to `gh pr create --body-file -` |

Every command is non-interactive, prints no secrets, and exits 0 on success, 1 on a failure of the thing checked
(a failed check, a run whose gate refused), 2 on a usage or configuration error, so an agent can branch on it
without parsing prose.

`results` reads the counts (`matrix.py counts` of each arm) and the reports; by default it prints labels, counts and
reasons only. A reason may quote a canary, as the viewer does; both are the workspace owner's, like the chats.

## Conventions an agent can follow without asking

- **Names derive from one name.** Given `<name>`: the experiment `experiments/<name>.yml`, the mitigation id
  `<name>` (unless it reuses one), its switch `spe_mitigate_<name with _>`, its tests
  `tests/experiments/<name>.yaml`, its branch `experiment/<name>`, its template `spe-x-<name>`.
- **Templates for every file**: `threats/TEMPLATE.md` (exists), `paths/TEMPLATE.md`, `mitigations/TEMPLATE.yml`,
  `experiments/TEMPLATE.yml`, each with a comment per key; `spe-eval new` fills them.
- **One check before every push**: `check_experiment.py <name>` exits 0.
- **A run needs the workspace alone**: the agent says so to the person before `spe-eval run` (chats are reset by
  the restores), and does not `spe-apply` while the lock is held (it would be refused).

## Acceptance

An agent given only the workspace and the sentence "propose a mitigation for TM-003 through P2 and measure it" can
reach a pushed `experiment/<name>` branch with a passing checker and a filled PR body, using only the commands
above and the workspace guide. The plan's last slice checks this end to end, with a coding agent in a de.NBI
workspace, and records where it needed help.
