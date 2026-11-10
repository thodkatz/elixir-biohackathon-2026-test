# platform/instance

What runs on an instance from the repository clone there (`spe_repo_dir`,
`/home/ubuntu/sperange`):

| Path | What |
|---|---|
| `compose.yml` | The `spe-frontend` compose project: both chats and the sandbox they share, selected by `COMPOSE_PROFILES` in the frontend directory's `.env`. Linked as `spe_frontend_dir/docker-compose.yml`; mounts the runbook, the prompt and the agent's source from the clone |
| `compose.<name>.yml` | Compose overlays a canary ladder switch adds to the `spe-frontend` project, e.g. `compose.eval-sink.yml` (`spe_eval_sink`: the sandbox resolves the test receiver's name to the VM). The `.env`'s `SPE_COMPOSE_OVERLAYS` (`eval-sink,…`, absent by default) selects them; `spe-apply` passes each with `-f` after `compose.yml` |
| `spe-apply` | Builds the images from the clone and recreates the containers; `stack`, `all` and `ansible` run the Ansible roles on the VM against itself with `instances/local.yml`, written at creation, and all three pass extra arguments through to `ansible-playbook`. On a `spe-experiments` build, every command refuses while an `spe-eval run` or `arm` holds `~/spe-eval/lock` (experiments spec part 03, decision 11), unless `SPE_EVAL_LOCK` names the holder's own token. Linked as `/usr/local/bin/spe-apply` |
| `spe_eval.py` | `spe-eval`'s core library (experiments spec part 03): loading an experiment and checking it against this build (decision 7), the two arms' `-e` values (decision 9), the generated agent suite (R1), the run id/reports layout and the lock (decision 11). Standard library plus PyYAML only; no CLI yet |
| `workspace/AGENTS.md` | The guide for Coder Agents in a workspace: what is live, what needs `spe-apply`, what needs a new template, how to verify |
| `workspace/skills/` | Skills for Coder Agents, linked as `~/.agents/skills/` |

A change in the clone is testable in the instance's chat without rebuilding the
instance. The table in `../coder/README.md`, "Working in a workspace", says what
each change needs.
