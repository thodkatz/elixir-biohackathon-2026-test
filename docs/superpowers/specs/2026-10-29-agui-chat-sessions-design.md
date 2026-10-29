# AG-UI chat sessions — design

**Status:** draft (PR #7). **Latest clarification:** none.
Read against this repo at `ff3acc3` (`main`, equal to `upstream/main` plus the fork's files and the
optional token cap of upstream PR #9).

**Who reads it:** whoever plans or implements the chat UI in `platform/agui/copilotkit-chat/`, the `agui` and
`run_archive` Ansible roles, and whoever analyses archived AG-UI runs.

**Problem.** The CopilotKit chat (`spe_frontend: agui`) is one conversation that a reload throws away
(`docs/specs/2026-10-15-agui-frontend-design.md`, §6: "no persistence"). Participants cannot keep several
attempts apart, come back to one, or label them, as Open WebUI lets them. And because nothing is stored,
the run archive keeps nothing of an AG-UI run (`platform/coder/README.md`: "The `agui` frontend is not
archived"), so what participants tried is lost for later analysis.

**Decision.** The chat UI gets an Open WebUI-style sidebar of sessions: list, open, new, rename, search,
pin, tags (add, remove, filter), hide and delete. Each session is one JSON file on a `chat-sessions` volume
of the `chat-ui` container. Its conversation is recorded **on the server**, in the CopilotKit runtime
route, from the agent's AG-UI event stream; the browser only changes metadata. Delete removes a session
from the participant's view but keeps the file, marked deleted. `archive.yml` gains an `agui` export that
copies every session and the agent's run log into the run directory, rendered like an Open WebUI run.

## Decisions taken

| # | Decision | Section | Acceptance check |
|---|---|---|---|
| 1 | One JSON file per session, `/data/sessions/<uuid>.json` on volume `chat-sessions`, schema `version: 1`; root filesystem stays read-only | [Storage](#1-storage-and-the-session-record) | `npm test`: a recorded run produces a file that validates against the schema; `docker inspect` on an instance: `chat-ui` has `ReadonlyRootfs: true` and one writable mount, `/data` |
| 2 | Session ids are canonical UUIDs; nothing else ever names a file | [Storage](#1-storage-and-the-session-record) | `npm test`: ids like `../x`, `a/b`, upper-case or non-v4 strings get 400 from every route and a refused run from the recorder; no file is created |
| 3 | Writes are atomic (temp file + rename in the same directory) and serialised per session | [Storage](#1-storage-and-the-session-record) | `npm test`: a write interrupted before the rename leaves the previous file intact; 20 concurrent metadata updates to one session all land |
| 4 | The conversation is recorded by the server from the run stream, after every run, whatever its outcome | [Recording](#2-recording-and-the-session-api) | `npm test` with scripted event sequences: finished, failed (`RUN_ERROR`) and cancelled (stream unsubscribed) runs each leave `messages` and a `runs[]` entry with that status; end-to-end against `fake_agent.py`: closing the tab mid-run still leaves the run's messages on disk |
| 5 | The browser changes metadata only, through `/api/sessions` (`GET` list, `GET`/`PATCH`/`DELETE` one); no `POST`: a session exists once its first run is recorded | [Recording](#2-recording-and-the-session-api) | `npm test`: `PATCH` with `messages`, `runs`, `id` or any unknown key gets 400 and changes nothing; a new UUID is absent from `GET /api/sessions` until a run on it ends |
| 6 | Delete is a soft delete: `deleted_at` set, the session gone from every API answer and refused for new runs, the file kept and archived | [Recording](#2-recording-and-the-session-api) | `npm test`: after `DELETE`, list omits it, `GET`/`PATCH`/`DELETE` give 404, a run on its id ends with `RUN_ERROR` and does not reach the agent; the file still exists with `deleted_at` |
| 7 | Titles start as the first user message cut to 60 characters and are never overwritten once the user renames | [Storage](#1-storage-and-the-session-record) | `npm test`: auto title after the first run; after `PATCH {title}` (`title_source: "user"`) a later run leaves it unchanged |
| 8 | Tags are normalised (trim, lower-case, `[a-z0-9._-]`, ≤ 32 chars, ≤ 20 per session, de-duplicated) | [Storage](#1-storage-and-the-session-record) | `npm test`: table of inputs → stored tags or 400 |
| 9 | The sidebar: new chat, title search, tag filter (all selected tags must match), pinned first then date groups, row menu (rename, pin, tags, hide, delete with confirmation), show-hidden toggle; the open session is in the URL (`?session=`) | [Sidebar](#3-the-sidebar) | Playwright run against `fake_agent.py`: each action, then a reload reopens the same session with its tool cards; screenshots in the plan's progress file |
| 10 | Switching session and New chat are disabled while a run is in progress | [Sidebar](#3-the-sidebar) | Playwright: during a scripted slow run both controls are disabled; after stop they are enabled and the stopped run is recorded as `cancelled` |
| 11 | `archive.yml` exports, for `spe_frontend: agui`, every session file (hidden and deleted included) and the agent's `runs.jsonl`; a missing `chat-ui` container fails the export | [Archive](#4-the-archive) | On the dev VM: `archive.yml` after the Playwright run gives a run directory with one `agui-sessions/<id>.json` per file on the volume and `agent-runs.jsonl`; with `chat-ui` removed, `archive.yml` fails and `destroy.yml` deletes nothing |
| 12 | `write_agui_run.py` renders the bundle in the Open WebUI run layout: `index.md`, `chats/NN-<title>.md` and `.json`, plus the raw files; re-runnable on an archived run | [Archive](#4-the-archive) | `pytest platform/dev/tests -k agui_run`: a fixture with active, hidden and deleted sessions renders the expected index rows and state, a deleted marker, fenced tool calls; a second run on the output directory gives identical files |
| 13 | Session files and the archive hold messages and run metadata only: no request headers, no keys | [Security](#5-security-and-limits) | `npm test`: a run whose request carries `Authorization` and whose events carry the test agent key leaves neither header nor key in the file (the agent's own redaction is not relied on: the recorder never stores headers, and the test key appears only in a header); `checks.yml`'s existing key scan extended to the volume |
| 14 | Model text is rendered as text in the sidebar and fenced in the archive | [Security](#5-security-and-limits) | `npm test`/Playwright: a title of `<img src=x onerror=…>` shows as literal text; pytest: a tool result containing a ``` fence renders inside a longer fence |
| 15 | No-cost instance check: the session API answers | [Testing](#6-testing) | `verify.yml` on an `agui` instance: "Session API answers" passes (`GET /api/sessions` → 200, JSON list) |

## Early output

The plan builds first, against `platform/dev/fake_agent.py` (no model calls): **the sidebar with three
sessions** (one tagged and pinned, one hidden, one deleted) **and the run directory `archive.yml`
writes for them** (`index.md` and one `chats/NN-*.md`). The user looks at both: the page for whether the
sidebar is the Open WebUI subset they want (decision 9), the run directory for whether it is what they
would read when analysing what participants tried (decision 12). Either can change the layout, the row
menu or what the archive renders, before the rest is built on it.

## Glossary

| Term | Meaning |
|---|---|
| session | one conversation in the sidebar; one AG-UI thread; one file on the volume |
| thread id | the AG-UI `threadId` of a session's runs; equal to the session id, a UUID chosen by the browser |
| recorder | the server-side hook on the `spe` agent's AG-UI stream that writes `messages` and `runs[]` |
| metadata | `title`, `tags`, `pinned`, `hidden` (changed by the browser) and `deleted_at` (set by `DELETE`) |
| hidden | removed from the default list, shown with *Show hidden*; still openable and editable |
| deleted | `deleted_at` set: invisible to the participant and the API, kept on disk and in the archive |
| run log | the agent's `runs.jsonl` (`platform/agui/pydantic-ai-agent/README.md`, *Run log*) |

## 1. Storage and the session record

Each session is one file, `/data/sessions/<id>.json`, on a new named volume `chat-sessions` mounted at
`/data` in `chat-ui` (`roles/agui/templates/docker-compose.yml.j2`), owned by uid 1000. The container
keeps `read_only: true`, its tmpfs mounts, `cap_drop: ALL`, `no-new-privileges` and its limits.

`<id>` is the session's thread id: a canonical lower-case UUID (v4, as `crypto.randomUUID()` makes). The
store refuses every other string before building a path, so no request input reaches the filesystem
except as a validated UUID.

```json
{
  "version": 1,
  "id": "6f1c0d2e-…",
  "title": "List the home directory",
  "title_source": "auto",
  "tags": ["exfil", "dns"],
  "pinned": false,
  "hidden": false,
  "created_at": "2026-10-29T10:02:11Z",
  "updated_at": "2026-10-29T10:14:40Z",
  "deleted_at": null,
  "messages": [],
  "runs": [{ "run_id": "…", "started_at": "…", "ended_at": "…", "status": "completed" }]
}
```

- `messages` is AG-UI `Message[]` (user, assistant with tool calls, tool results) exactly as the run ended
  with it; reopening a session passes it to `agent.setMessages()` unchanged.
- `runs[]` has one entry per recorded run; `status` is `completed`, `failed` or `cancelled`, as in the run
  log. `run_id` and the file's `id` (= `thread_id`) join a session to its run-log lines. The run log stays
  the authoritative record of tool calls; the session is the conversation as the participant saw it.
- `title`: the first user message's text, whitespace collapsed, cut to 60 characters (`title_source:
  "auto"`), set when the session's first run is recorded; `"Untitled"` if it has no text. A `PATCH` sets
  `title_source: "user"`; the recorder never changes a user title. Titles are at most 200 characters.
- `tags`: each trimmed, lower-cased, matching `[a-z0-9._-]{1,32}`, at most 20, de-duplicated, kept in the
  order given. An invalid tag makes the whole `PATCH` fail with 400.
- `updated_at` changes on every write; the list is ordered by it, newest first.

**Writes** go to `<id>.json.tmp-<random>` in the same directory, then `rename` over `<id>.json`, so a file
is never half-written. A per-id promise chain in the Node process serialises writes to one session
(read-modify-write included). `chat-ui` is one Node process (`node .next/standalone/server.js`), so no
cross-process lock is needed; the spec assumes it stays one, and the plan notes it next to the queue.

Each run rewrites the whole file. A long session with large tool results (each already capped by the
agent's `tools.max_output_bytes`) stays within a few MB; there is no size limit per file (see
*Security and limits*).

## 2. Recording and the session API

### Recorder

The `spe` agent in `app/api/copilotkit/[[...slug]]/route.ts` gets a recorder on its AG-UI stream: AG-UI
`Middleware` (`runNextWithState`, which yields the messages after each event) attached with
`agent.use(...)`, or an `HttpAgent` subclass overriding `run()` and `clone()`. The runtime clones the agent
per request (`cloneAgentForRequest`), so the plan's first task checks which of the two survives the clone,
with a test; the middleware is preferred because it uses AG-UI's public API.

For each run:

1. **Start.** Validate `input.threadId` as a UUID; read the session. If the id is invalid, or the session is
   deleted, emit `RUN_STARTED` then `RUN_ERROR` ("invalid session" / "this session was deleted") and do
   not call the agent. A missing file is a new session: create it in memory with the auto title from
   `input.messages`.
2. **During.** Keep the latest messages from each event.
3. **End**, on `RUN_FINISHED`, `RUN_ERROR`, or unsubscription (the browser went away or the run was
   stopped): write `messages` and append `runs[]` with `completed`, `failed` or `cancelled`. On a terminal
   event the write completes before that event is passed on; on unsubscription it runs after. A write
   error is logged on the server (`console.error`, no message content); the only change it makes to the
   stream is the `spe.session_save_failed` event (*Security and limits*).
   The run log in the agent records the run either way.

**What the record means.** AG-UI clients send the whole history with every run, and the agent trusts it
(`pydantic-ai-agent/README.md`, *Runs*). So `messages` is exactly what the agent was sent plus what it
returned. A participant who rewrote the browser's history would appear as that rewritten history: the
record says what the agent saw, not more. The run log's per-run tool calls are the cross-check.

### Session API

Routes under `app/api/sessions/`, beside `/api/copilotkit`:

| Call | Answer |
|---|---|
| `GET /api/sessions` | `200`, a JSON list of metadata (`id`, `title`, `tags`, `pinned`, `hidden`, `created_at`, `updated_at`), deleted sessions left out, hidden ones included, newest `updated_at` first, at most 1000 |
| `GET /api/sessions/{id}` | `200` with the full record minus `deleted_at` and `runs`; `404` if missing or deleted |
| `PATCH /api/sessions/{id}` | body: any of `title`, `tags`, `pinned`, `hidden`; `200` with the new metadata; `400` for an unknown key, a wrong type or an invalid value (nothing changed); `404` if missing or deleted |
| `DELETE /api/sessions/{id}` | sets `deleted_at`; `204`; `404` if missing or already deleted |

An id that is not a UUID gets `400`. Bodies over 16 KB get `413`. Error bodies are
`{"error": "<generic message>"}` and never contain paths or stack traces; details go to the server log.

**No authentication of its own.** The chat UI has none: it is reached only through the SSH tunnel to
`127.0.0.1:{{ spe_agui_ui_port }}` or the Coder proxy, one participant per instance. The session API sits
behind the same boundary. If an instance ever serves several participants, sessions need an owner; that
is out of scope here (*Out of scope*).

## 3. The sidebar

Plain React and CSS in `app/` (no new dependencies); all session data is rendered as React text.

- **Layout:** a left sidebar (about 260 px, collapsible) and the chat to its right. Top to bottom: *New
  chat*; a search box filtering by title (case-insensitive substring, in the browser); tag chips for every
  tag in use with a count, where selecting several shows sessions that have all of them; the list, pinned
  first, then grouped *Today*, *Yesterday*, *Previous 7 days*, *Older* by `updated_at`, each row with title
  and tags, the open one highlighted; at the bottom a *Show hidden* toggle and the note "Deleted sessions
  are kept in the run archive."
- **Row menu (`⋯`):** *Rename* (inline; Enter saves, Esc cancels), *Pin* / *Unpin*, *Tags* (add with an
  input suggesting existing tags; remove with a chip's ×), *Hide* / *Unhide*, *Delete* (confirmation: "This
  removes it from your list. It is kept in the run archive.").
- **Chat header:** replaces today's one-line banner: the session's title and tags, editable there too, and
  the note that every tool call is shown.
- **Open session in the URL:** `?session=<id>`. Loading the page with it fetches the session; without it,
  or with an id that answers 404, the page starts a new session (and drops the parameter).
- **Opening a session:** `GET /api/sessions/{id}`, then CopilotChat's `threadId` set to the id and
  `agent.setMessages(messages)`; the tool cards render again from the stored tool-call messages. **New
  chat:** a fresh `crypto.randomUUID()` and an empty history; the session joins the list when its first
  run is recorded.
- **During a run** (the agent's `isRunning`), switching and *New chat* are disabled, so a run never ends
  in a session the participant has left. CopilotChat's stop button ends the run (recorded `cancelled`).
- **Refresh:** the list is fetched on load, after each run ends and after each metadata change; no polling.
- **Errors:** a failed API call shows in the existing error bar; the open chat is never cleared. A run
  refused by the recorder shows its `RUN_ERROR` there as today.

The README's "No persistence: a reload starts a new conversation" and the header text are rewritten; the
2026-10-15 spec's §6 line is history and stays, with this spec named as superseding it in the plan's
progress record.

## 4. The archive

Same shape as the Open WebUI path in `roles/run_archive`: export on the VM, fetch, write on the
controller.

**Export** (`tasks/export.yml`, new block when `spe_frontend == 'agui'`; `archive.yml`'s play name
becomes "Export the frontend's chats"):

1. `docker compose -p spe-frontend cp chat-ui:/data/sessions <tmp>/sessions` and
   `docker compose -p spe-frontend cp agent:/var/lib/spe-agent/runs.jsonl <tmp>/agent-runs.jsonl` (a
   missing run log is allowed: no run yet).
2. Pack `<tmp>` into `/tmp/spe-agui-export.tar.gz`, fetch it to
   `{{ spe_output_dir }}/archive-bundle-agui.tar.gz`, remove both from the VM.

Every file is exported, hidden and deleted included. The containers are still up when `archive.yml` runs
(`destroy.yml` imports it first; the Coder stop runs `destroy.yml`). If `chat-ui` does not exist the copy
fails, `archive.yml` fails, and `destroy.yml` deletes nothing, as for Open WebUI today.

**Write** (`tasks/write.yml`): when the agui bundle exists, unpack it and run
`files/write_agui_run.py <bundle dir> <run dir>` (stdlib only, like `write_run.py`):

```
<run dir>/
  run.yml                    as today
  index.md                   sessions table: #, title, tags, created, runs, state (active / hidden / deleted <time>)
  chats/NN-<slug>.md         user and assistant text; each tool call with fenced arguments and result
  chats/NN-<slug>.json       the session record as stored
  agui-sessions/<id>.json    the raw files, untouched
  agent-runs.jsonl           the agent's run log
```

`NN` follows `created_at`. A deleted session's `.md` opens with "Deleted by the participant at <time>."
Slugs and fences reuse `write_run.py`'s rules. `index.md` says that the AG-UI frontend has no run report.
Given an archived run directory (`agui-sessions/` and `agent-runs.jsonl` present), the script re-renders it
in place. The *Overview without a chat export* task stays for runs with no bundle (no frontend), with its
text corrected. `archive-bundle-agui.tar.gz` is removed after writing, like `archive-bundle.json`.

`platform/coder/README.md` ("The `agui` frontend is not archived"), `platform/ansible/README.md`,
`AGENTS.md` (*AG-UI agent frontend*: "Not done yet: archiving its chats on stop") and
`docs/getting-started.md` are updated in the same slice.

## 5. Security and limits

- **Isolation unchanged.** `chat-ui` gains only `/data`. The agent and sandbox cannot reach the volume
  (other containers; the sandbox is on `tools` only). The model supplies text, never a path.
- **No keys in sessions.** The recorder stores `messages` and run metadata, never request headers, the
  agent key (`AGENT_API_KEY`) or the runtime configuration. Tool results may contain canary values and
  dataset content, as Open WebUI's export does; the run directory's existing handling applies to
  `agui-sessions/` and `agent-runs.jsonl` (outside git, treated like `canaries.json`). `checks.yml`'s key
  check gains the volume: no file under `/data/sessions` contains the agent key, the LLM key or the
  sandbox key.
- **Untrusted text.** Titles, tags and messages render as React text, never as HTML; the chat's own
  message rendering is unchanged. `chats/*.md` fences tool arguments and results with a fence longer than
  any run of backticks inside.
- **Input limits:** `PATCH` bodies ≤ 16 KB, titles ≤ 200 characters, tags as in §1, ids UUID-only, the list
  capped at 1000.
- **Size and failures.** No per-file limit. A failed write (disk full) is logged; the next list fetch
  cannot show what was not written, and the error bar says "this session could not be saved" when the
  page learns of it: the recorder emits a `CUSTOM` event named `spe.session_save_failed` before the
  terminal event (the write happens before the terminal event is passed on, for this reason). The run log
  still has the run.
- **Lifetime.** Only `destroy.yml` removes the volume (*Compose stacks down, with their volumes*), and only
  after `archive.yml` succeeded.

## 6. Testing

- **Chat UI unit tests**, no new dependencies: the store, validation and recorder live in `lib/`
  (`lib/sessions.ts`, `lib/recorder.ts`), with `lib/*.test.ts` run by `node --test` (Node 24 strips types)
  as `npm test`. They cover decisions 1–8, 13 and the text rendering of 14. `npm run build` stays the type
  check. `AGENTS.md`, *Running things*, gains `(cd platform/agui/copilotkit-chat && npm ci && npm test)`.
- **Archive writer:** `platform/dev/tests/test_write_agui_run.py` (pytest) over a fixture bundle with
  active, hidden and deleted sessions and a run log (decision 12, 14).
- **End to end, no model:** the built chat UI against `platform/dev/fake_agent.py`, driven by Playwright
  through every sidebar action (decisions 9, 10), with the files checked after each step; screenshots and
  the result in the plan's progress file. This is also the early output.
- **On an instance:** the new no-cost check in `roles/agui/tasks/checks.yml` (decision 15) and the
  extended key check (decision 13); then, on the dev VM, `archive.yml` after the Playwright run
  (decision 11). The existing smoke run calls the agent directly, not through `chat-ui`, and stays as is.
- **One paid check, with the user's OK at the time:** a two-turn chat in the browser on the dev VM
  (`claude-haiku-5-5`), then `archive.yml`; about $0.01.

## Out of scope

- **Sessions with owners** (several participants per instance): needs identity in the chat UI; with
  `BACKLOG.md`'s per-user budgets item, as both wait for multi-participant instances.
- **A run report** in the CopilotKit chat (Open WebUI's "Run report" note): still not done, as
  `AGENTS.md` says; `index.md` states it.
- **Upstream.** The code and its READMEs refer to nothing fork-only, so the work can go upstream as one PR
  cut from `upstream/main` (`AGENTS.md`, *Contributing upstream*), carrying a README section instead of this
  spec.
- **Branching, editing or regenerating messages**, export from the UI, full-text search over messages,
  folders: Open WebUI features not asked for.

## Inputs for the plan

- Slices, in order: (1) store, API and recorder with unit tests, plus the volume in the compose template;
  (2) the sidebar and the Playwright run, which produces the early output with (3); (3) the archive export,
  `write_agui_run.py` and its tests, the instance checks, and the README/AGENTS.md updates. The early output
  needs (1)–(3)'s minimum, so the plan may build a thin version of (2) and (3) first.
- First task of slice 1: which recorder form survives `cloneAgentForRequest` (middleware vs subclass),
  pinned by a test; rule in the progress file if neither does, with the browser-save fallback (the page
  `PUT`s `agent.messages` after each run) as the recorded cost.
- How CopilotChat 1.79 reacts to a changed `threadId` together with `agent.setMessages()` (remount via
  `key`, or not) is checked in slice 2's first task.
- The fake agent may need a slow scripted run for decision 10's check.
