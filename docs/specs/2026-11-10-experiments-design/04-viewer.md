# The viewer and its app

## `evals-view`

Two compose services in `platform/instance/compose.yml`, profile `evals`, on every instance built with
`spe_experiments` (02): `evals-view` (its proxy, *Read-only* below) listens on `127.0.0.1:<SPE_EVALS_PORT>` only,
on a compose network of its own, joined by no other service; `evals-promptfoo` shares that network namespace
instead of joining it itself, and:

- runs `promptfoo view` at the version `platform/promptfoo-evals/package.json` pins (0.125.1), built from that
  directory's lock file, so viewer and runs agree on the database schema;
- reads `~/spe-eval/promptfoo` (bind mount), which `spe-eval` writes as `PROMPTFOO_CONFIG_DIR`: evals appear when
  they are written, with no import step;
- has in its environment `PROMPTFOO_DISABLE_SHARING=1`, `PROMPTFOO_DISABLE_TELEMETRY=1`,
  `PROMPTFOO_DISABLE_UPDATE=1`, and no provider, agent or LLM key.

The isolation reset neither restores nor recreates either: neither is in `isolation.VOLUMES` nor `CONTAINERS`, and
the eval data is a bind mount, not a volume, so there is nothing to snapshot.

## Read-only

`promptfoo view` can start evals (`POST /api/eval/job`, the eval creator's Run button), replay a test with edited
input (`POST /api/eval/replay`) and change stored results. A run from the viewer would bypass `spe-eval`: no
checks, no gate, no lock. A small proxy in front of it (the service's entry point) forwards `GET` and `HEAD`
everywhere, plus the one write the reading UI itself needs: socket.io's own transport, `POST /socket.io/`
(long-polling; the server registers only `connection` and emits `init`/`update`, it handles no client event),
alongside the websocket upgrade on `GET /socket.io/`. Every other request gets 403, including every write
`promptfoo view` itself offers (`POST /api/eval/job`, `POST /api/eval/replay`, `PATCH`/`DELETE /api/eval/:id`,
`POST /api/user/email`, …). This allow-list was settled against 0.125.1's routes themselves
(`dist/src/server/index.js`) and its web app bundle: the default is to refuse. `platform/dev/tests/test_evals_view.py`
runs nginx in front of a stub upstream and checks every one of 0.125.1's routes against it — every non-GET route
gets 403 (socket.io's POST excepted), every GET route 200 — with the route list checked against `node_modules`
when it is present. The proxy forwards the normalized `$uri`, not the client's raw request path, so an encoded
path (`..%2F`) cannot reach a write route by way of `/socket.io/`'s allowance. The proxy is configuration of an
existing reverse proxy (an allow-list of methods and paths), not code of our own. Without keys a run would fail
anyway; the proxy makes it refuse plainly instead.

`evals-view` (above) is a stock `nginx:1.29-alpine` image, configuration only (`evals-view/nginx.conf`); it owns
the network namespace, and `evals-promptfoo` shares it rather than joining the `evals` network itself, so its
port (15500) is reachable only through this proxy, never directly. Two containers rather than one because the
proxy is a stock image and not our code, `promptfoo view` needs Node, which that image does not have, and
sharing one network namespace keeps promptfoo's own port off every network (clarification 3).

## The app

One app, **Evaluations**. Runs are started with `spe-eval run` (07), by the participant's coding agent or in the
workspace terminal; a button that only types that command adds nothing, and would start a run nobody asked to
detach or watch.

```hcl
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

Evaluations is owner-only, like the chats: the results hold canaries and the agent's answers.

## What it does not show

The ladder's matrix across levels (`matrix.py render`) is not promptfoo's: it needs levels and conditions from the
hand-off. It stays a command (`matrix.py counts` per run, `render` over them), and the contribution's PR carries its
counts (05).
