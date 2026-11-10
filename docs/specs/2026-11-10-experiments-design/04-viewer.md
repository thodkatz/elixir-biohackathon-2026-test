# The viewer and the apps

## `evals-view`

A compose service in `platform/instance/compose.yml`, profile `evals`, on every instance built from the portal:

- runs `promptfoo view` at the version `platform/promptfoo-evals/package.json` pins (0.125.1), built from that
  directory's lock file, so viewer and runs agree on the database schema;
- reads `~/spe-eval/promptfoo` (bind mount), which `spe-eval` writes as `PROMPTFOO_CONFIG_DIR`: evals appear when
  they are written, with no import step;
- listens on `127.0.0.1:<SPE_EVALS_PORT>` only, on a compose network of its own, joined by no other service;
- has in its environment `PROMPTFOO_DISABLE_SHARING=1`, `PROMPTFOO_DISABLE_TELEMETRY=1`,
  `PROMPTFOO_DISABLE_UPDATE=1`, and no provider, agent or LLM key.

The isolation reset neither restores nor recreates it: it is in neither `isolation.VOLUMES` nor `CONTAINERS`, and
is listed in `NOT_RESTORED` with its reason.

## Read-only

`promptfoo view` can start evals (`POST /api/eval/job`, the eval creator's Run button), replay a test with edited
input (`POST /api/eval/replay`) and change stored results. A run from the viewer would bypass `spe-eval`: no
checks, no gate, no lock. A small proxy in front of it (the service's entry point) forwards `GET`
and the few writes the reading UI needs, and answers 403 to everything else. Which writes the reading UI needs is
settled by the plan with a test against 0.125.1's routes (`dist/src/server/index.js`): the default is to refuse.
Without keys a run would fail anyway; the proxy makes it refuse plainly instead.

## Apps

```hcl
resource "coder_app" "run_evaluation" {
  agent_id     = coder_agent.main.id
  slug         = "run-evaluation"
  display_name = "Run evaluation"
  command      = "spe-eval run; echo; echo '== Evaluation finished. Close this tab, or use this shell.'; exec bash -l"
}

resource "coder_app" "evaluations" {
  agent_id     = coder_agent.main.id
  slug         = "evaluations"
  display_name = "Evaluations"
  url          = "http://localhost:<SPE_EVALS_PORT>"
  subdomain    = true
  share        = "owner"
  healthcheck { url = "http://localhost:<SPE_EVALS_PORT>/" interval = 10 threshold = 30 }
}
```

Run evaluation ends in a shell for the reason Rebuild does: the web terminal reruns its command on reconnect, so
a bare command would start a second run (which the lock would refuse, but noisily). Evaluations is owner-only, like
the chats: the results hold canaries and the agent's answers.

## What it does not show

The ladder's matrix across levels (`matrix.py render`) is not promptfoo's: it needs levels and conditions from the
hand-off. It stays a command (`matrix.py counts` per run, `render` over them), and the contribution's PR carries its
counts (05).
