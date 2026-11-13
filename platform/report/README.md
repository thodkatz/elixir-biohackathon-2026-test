# The run report service

`sperange_report.py` serves the run reports and the runs browser of the portal at
`https://sperange.bihealth.org/reports/…`. Caddy forwards everything under `/reports`
to it (port 7090). Every portal user can read everything here; only a report's owner
and portal admins can write it. Design: `docs/specs/2026-11-06-run-report-service.md`
and `docs/specs/2026-11-10-runs-browser.md`.

| | |
|---|---|
| `sperange_report.py` | The service (standard library plus `python3-markdown` and `python3-yaml`) |
| `static/` | The pages' CSS and scripts, the runs browser (`runs.js`, `runs.css`) and the vendored EasyMDE editor |
| `tests/` | `pytest` against a fake Coder API |
| `threat_model.json` | The threat-score classifier, a copy of the agent's (`../agui/threat-score/README.md`; a test keeps the two equal) |
| `../coder/deploy/sperange-report.service`, `report.env.example` | The systemd unit and its env file (`REPORTS_DIR`, `RUNS_DIR`, `HITS_DIR`, `CODER_URL`, `LISTEN`, optionally `THREAT_EMBEDDINGS_URL` and `THREAT_EMBEDDINGS_KEY`) |
| `canary_watch.py`, `canary_reader.py`, `canary_record.py`, `canarymatch.py`, `canary_hits.py` | The canary hit viewer's watcher: see *Canary hit watcher* below |
| `hits_view.py` | Renders a hit to HTML, the participant page's body and the admin page's (its workspace rows), and reads the hits root and the watcher's status files; used by both the watcher (`--html`, the standalone early output) and `sperange_report.py` (both pages, *Canary hits pages* below) |
| `../coder/deploy/sperange-canary-watch.service` | The watcher's unit |
| `../ansible/roles/run_report/` | Writes the report and its sidecar at the first build of a workspace |
| `../ansible/reports/run_report.md.j2` | The template the report starts from |

## Logging in

The service asks Coder who you are. In the browser the `coder_session_token` cookie
from the portal login does that. From a script, send a Coder token in the
`Coder-Session-Token` header (make one with `coder tokens create`, or use the CLI's
own token in `~/.config/coderv2/session`):

```bash
TOKEN=$(cat ~/.config/coderv2/session)
curl -s -H "Coder-Session-Token: $TOKEN" https://sperange.bihealth.org/reports/api/runs
```

Without a login, a page redirects to the portal login; an API or `.md` request
answers `401` with `{"error": "not logged in"}`.

## Pages

| Route | What it is |
|---|---|
| `GET /reports/` | The list of live reports, one per workspace |
| `GET /reports/<workspace id>` | One report: the EasyMDE editor for the owner and admins, read-only for everyone else |
| `GET /reports/runs` | The runs browser: every archived run, one run with its report and chats, one chat as turns. Its views are hash routes: `#/run/<run>`, `#/run/<run>/chat/<frontend>/<chat>`, `#/workspace/<workspace id>` |
| `GET /reports/healthz` | `200 ok`, no login |

A workspace's "Report" button opens `/reports/<workspace id>`; its "Archived chats"
button opens `/reports/runs#/workspace/<workspace id>`.

## Live reports

| Route | What it does |
|---|---|
| `GET /reports/<workspace id>.md` | The report's Markdown. The `ETag` header is the SHA-256 of the file |
| `PUT /reports/<workspace id>.md` | Saves the report. Body: the Markdown (UTF-8, under 1 MB). `If-Match` with the ETag you read is required; `412` if the file changed meanwhile, `403` unless you are the owner or an admin. Answer: `{"etag", "saved"}` |
| `POST /reports/preview` | Markdown in, the same sanitized HTML fragment the pages show out |
| `GET /reports/api/reports` | `{"reports": [...]}`: every live report with `workspace_id`, `workspace`, `owner`, `instance`, `created`, `parameters`, `template_sha256`, `last_saved` |

Reading and saving a report from a script:

```bash
URL=https://sperange.bihealth.org/reports/<workspace id>.md
curl -s -D headers.txt -o report.md -H "Coder-Session-Token: $TOKEN" $URL
ETAG=$(grep -i '^etag' headers.txt | cut -d' ' -f2 | tr -d '\r')
# edit report.md, then:
curl -s -X PUT -H "Coder-Session-Token: $TOKEN" -H "If-Match: $ETAG" --data-binary @report.md $URL
```

`PUT` and `POST` from a browser must come from the portal's own origin.

## Archived runs

`playbooks/archive.yml` writes one directory per stopped workspace under `RUNS_DIR`
(default `/data-share/runs`). The API reads them as they are; `<run>` is the
directory name (`<UTC time>_<instance>`, for example
`2026-11-10T105525Z_cw-yasinmiran-chicken`), `<frontend>` is `openwebui` or `agui`,
`<chat>` the chat file's stem (`01-title`). The participant's e-mail and
`canaries.json` are never served.

| Route | What it returns |
|---|---|
| `GET /reports/api/runs` | `{"runs": [...]}`, newest first. One summary per run: `id`, `archived_at`, `instance`, `participant`, `workspace`, `model`, `flavor`, `frontends`, `workflows`, `samples`, `tiers`, `seed`, `chats` (count per frontend), `report` (`filled`, `workspace_id`) |
| `GET /reports/api/runs/<run>` | The summary plus `parameters` (all of `run.yml`), `chat_list` (every chat: `frontend`, `id`, `title`, `created`, `updated`, `messages`, `tags`, `archived`), `report` (`markdown`, `html`, `filled`, `workspace_id`, `created`) and `files` (`agent_runs`, `journals`) |
| `GET /reports/api/runs/<run>/report.md` | The report as archived, `text/markdown` |
| `GET /reports/api/runs/<run>/chats/<frontend>/<chat>` | One chat as turns: `title`, `meta`, `facts` (the key/value lines above the first turn), `turns` (each `role`: user, assistant, system, tool or section; `label`, `model`, `at`, `markdown`, `html`) and `links` to the two raw files |
| `GET /reports/api/runs/<run>/chats/<frontend>/<chat>.md` | The chat's Markdown as `write_run.py` rendered it |
| `GET /reports/api/runs/<run>/chats/<frontend>/<chat>.json` | The chat's export as archived (Open WebUI or AG-UI) |
| `GET /reports/api/runs/<run>/agui/agent-runs.jsonl` | The agent's run log, `application/x-ndjson` |
| `GET /reports/api/runs/<run>/agui/journals/<session id>.jsonl` | One AG-UI session journal as stored (the ids are in `files.journals`) |
| `GET /reports/api/workspaces/<workspace id>` | `{"workspace_id", "live_report", "runs"}`: the workspace's live report (as in `api/reports`, or `null`) and its archived runs, each with `chat_list`. A run belongs to the workspace when its archived report names the workspace id; older archives without that are matched by instance name |

**Threat scores.** With `THREAT_EMBEDDINGS_URL` (an OpenAI-compatible base URL) and
`THREAT_EMBEDDINGS_KEY` set, every user turn of a chat carries `threat`: `score` (0 to 100), `level`
(low, elevated, high) and `categories` (each `id`, `label`, `score`, `level`, `examples`, `auc`); the
chat carries `threat_model`, and each entry of a run's `chat_list` the highest score of its user
turns (`threat`: `score`, `level`). The runs browser shows them as chips; a click on a turn's chip
opens the categories. `THREAT_EMBEDDING_MODEL` (default `vllm/BAAI/bge-m3`) and `THREAT_MODEL`
(default `threat_model.json` next to the service) are optional. The texts are embedded on first
view, 32 per request, and the scores kept in memory. Without the variables, or when the endpoint
fails, the fields are absent. The scores are the classifier's, not a finding: it was trained on the
archived chats up to its date, so those score higher than new ones will.

Anything else under `/reports/api/` answers `404` with `{"error": "not found"}`.
The run listing is cached for ten seconds.

Examples:

```bash
H="Coder-Session-Token: $TOKEN"
B=https://sperange.bihealth.org/reports/api

curl -s -H "$H" $B/runs | jq '.runs[] | {id, participant, model, chats}'
curl -s -H "$H" $B/runs/<run> | jq '.chat_list'
curl -s -H "$H" $B/runs/<run>/chats/agui/01-title | jq '.turns[] | {role, at, markdown}'
curl -s -H "$H" $B/runs/<run>/chats/agui/01-title.json > chat.json
curl -s -H "$H" $B/runs/<run>/report.md
curl -s -H "$H" $B/workspaces/<workspace id> | jq '.runs[].id'
```

## Canary hit watcher

`canary_watch.py` is a separate unit (`../coder/deploy/sperange-canary-watch.service`,
`sperange-canary-watch`), not part of the report service: a daemon that polls every running Coder
workspace's instance over SSH (the reader, `canary_reader.py`, sent on stdin and run read-only) and
scans each stopped run's archive once, matching against the workspace's canary record
(`canary_record.py`, `canarymatch.py`) and writing hits, state and status under `<hits
dir>`, default `/data-share/canary-hits` (design: `docs/specs/2026-11-10-canary-hit-viewer.md`).
It reads: each workspace's report sidecar (`/data-share/reports/<id>.json`, to learn its
instance), that instance's output directory (`hosts.yml`, `canaries.json`), and each archived run
directory (`/data-share/runs/*_<instance>/`). It writes only under `<hits dir>`: a hits file
(`<id>.jsonl`, mode 0640), a state file (`<id>.state.json`, mode 0600) and a status file
(`<id>.status.json`, mode 0640) per workspace, never anything on the instance (decision 1,
*Nothing on the instance changes*) or in the run archive.

Three forms:

- **The daemon** (`canary_watch.py`, no flags needed beyond the defaults): `Watcher.run_forever()`,
  as the unit runs it.
- **`--archive RUN_DIR --out HITS.jsonl`**: scans one already-archived run directory into a hits
  file by hand (also used by tests and re-renders), optionally `--html PAGE.html` for a standalone
  participant page.
- **`--once --output-dir DIR --out HITS.jsonl`**: a hand check only, never run by the unit (the
  daemon never scans an instance without a report sidecar). One poll of `DIR`'s instance from zero
  offsets, through the real SSH transport,
  appending new hits to `--out`; no report sidecar, no state or status file, nothing written under
  `<hits dir>`. Prints the sources the reader found, what is missing, any source errors and the hit
  count per kind (an evaluation's hits counted apart, as `eval`) to stdout — never a token, an
  excerpt or a line of a source.

## Canary hits pages

`sperange_report.py` reads `<hits dir>/<workspace id>.jsonl` and `.status.json` (never writes
there; only the watcher does) to serve, narrower than the report (decision 10: the workspace's
owner and Coder owners only, 403 for everyone else, 401/redirect when logged out):

- `GET /reports/<id>/hits` — the participant page (`hits_view.participant_body`, HTML behind
  `static/hits.js` and `hits.css`): header, headline counts, the literal-matching notice, then
  the hits newest first. Every hit is a collapsed `<details>`: loud ones in the list, quiet ones
  under one "also seen (N)".
- `GET /reports/<id>/hits.json` — the same hits as JSON, `?after=<id>` for only the new ones.
- `GET /reports/<id>/hits/events` — the same hits live, as server-sent events: `event: hit` with
  the hit's id, kind, loudness, canary type, frontend and server-rendered HTML (one renderer,
  `hits_view.hit_html`, so a hit inserted live reads as one loaded with the page); `event: status`
  with the watcher's status line and `empty` (`hits_view.empty_text`, the text a hits list with
  none to show would use for this status, so a shown placeholder can be kept current). Sent again
  on change, and also every `stream_status_refresh` seconds (10) even when the status file is
  unchanged, so "watched N s ago" keeps ageing instead of freezing once the watcher stops touching
  it. Resumes past `Last-Event-ID` (else `?after=`); ends after 30 minutes (the browser
  reconnects) and refuses a 201st concurrent stream with 503.

`static/hits.js` opens the event stream, inserts each hit's HTML at the top of the list (no HTML
built in the browser but the server's own, parsed once from the event), keeps the headline counts,
the status line and an already-shown placeholder's text in sync, offers "Notify me" (kind and type
only, never the value or excerpt)
and "Group by run" (reorders the hits on the page, live ones included, by `data-session`/
`data-run`; builds no HTML of its own but the group headings. Only the loud hits are grouped —
"also seen" stays one collapsed block regardless). Both buttons are rendered `hidden` by
`hits_view.py` and shown once the script runs, so a page with no script (the standalone early
output, `--html`) never shows one that does nothing.

## Admin canary hits page

Coder owners only (403 for everyone else, 401/redirect when logged out, same rule as the
participant pages above); `/reports/` links to it ("Canary hits") for an admin, and shows no such
link to anyone else:

- `GET /reports/hits` — every workspace with hits or a status file, newest first
  (`hits_view.workspace_rows`): a table (name linking to that workspace's own `/hits` page, owner,
  instance, the viewer's Coder state for it, loud counts, quiet count, "Newest (detected)": the
  newest hit's `detected`, watcher status; a row with no state lookup or a failed one leaves that
  cell blank; a hits file that cannot be read shows as no hits, logged), the same banner as the
  participant page, then every workspace's hits merged, newest first by `detected` (the watcher's
  clock, not the instance's own `at`). Four filters (kind, type, frontend, workspace), applied in
  the browser over what the page already rendered. Capped at 500 hits (`ADMIN_PAGE_HITS`; "N more,
  older: ..." when capped — the rest are on each workspace's own page, uncapped).
- `GET /reports/hits.json` — the same rows and hits as JSON, hits capped at 2000
  (`ADMIN_JSON_HITS`).
- `GET /reports/hits/events` — the same hits live across every workspace, as server-sent events
  (`static/hits-admin.js`): rescans the hits directory on every poll, so a workspace that starts
  being watched mid-stream is picked up; a file already present when the stream opened starts at
  its end (no replay of old hits), one that appears later starts from its first line. Event id
  `<workspace>:<n>`; no status events. A hit for a workspace not in the opening table's row list
  bumps no count until the next reload. A workspace's hits file that cannot be read is dropped from
  the stream after one log line (the others keep streaming); the stream itself still ends if a
  followed file is replaced, cut or removed, same as the participant stream, and the page reloads
  to recover — at most once a minute per browser tab, so a flapping file does not reload in a loop.

## Running and testing

```bash
REPORTS_DIR=/tmp/reports RUNS_DIR=/tmp/runs CODER_URL=http://127.0.0.1:7080 python3 sperange_report.py
curl -I http://127.0.0.1:7090/reports/healthz
```

```bash
python3 -m venv .venv && .venv/bin/pip install pytest markdown pyyaml && .venv/bin/python -m pytest tests -q
```

On the portal VM the service runs as the systemd unit `sperange-report`; restart it
after a change: `sudo systemctl restart sperange-report`.
