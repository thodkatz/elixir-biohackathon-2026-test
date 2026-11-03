# AG-UI conversation record — design

**Status:** draft. **Latest clarification:** none.
Read against this repo at `1a30ac9` (`main`), with `@ag-ui/client` 1.0.2 and CopilotKit 1.79.0
(`@copilotkit/runtime`, `@copilotkit/react-core`) as pinned there, and Open WebUI v0.11.3 (the image
`spe_frontend_webui_image` pins) as the model to follow, read in its source at tag `v0.11.3` (`2a960a5`).

**Who reads it:** whoever plans or implements how the AG-UI chat (`platform/agui/copilotkit-chat/`, "`chat-ui`")
stores conversations, the archive (`roles/run_archive`), and whoever analyses archived AG-UI runs and needs to
know what the model was sent and what the participant tried to send.

**Problem.** In the AG-UI stack the browser holds the conversation and sends all of it with every run;
`chat-ui` forwards it to the agent, which trusts it (only system messages are replaced by the agent's own
prompt). A participant can therefore fabricate earlier turns, tool calls and tool results, edit or delete real
turns, or forge the agent's compaction marker (an assistant message whose id starts with `spe-compaction-`, which
makes the agent drop everything before it), with `curl` against `chat-ui`'s run route or with the browser's
devtools. The model sees the forgery, and nothing records it: `chat-ui` overwrites its stored copy of the session
with the client's latest history after each run, so the record shows the forged history as if it had happened,
and loses edited and deleted turns. A hard kill of `chat-ui` mid-run also loses that run, because the session is
written once, when the run ends.

**Decision.** `chat-ui` **owns the history**, as Open WebUI's backend does when it fronts an external agent: per
session it keeps an append-only **journal** of every run, written before the agent is called and as each event
arrives. For each run it takes from the client's request only the new user message, and sends the agent the
history from its journal. Everything else the client sent that differs from the journal is **ignored and
recorded** in full, with its kind (fabricated, edited, deleted). The agent stays stateless and unchanged. Two runs
on one session may run at once and become sibling branches. The sidebar and the session API keep their
behaviour and read the journal. The archive copies the journals raw and exports each one as an **Open WebUI
chat**, which the existing Open WebUI renderer turns into the same run layout, so both frontends are saved and
exported one way.

**What this protects, and what not.** It closes the history edits made through the chat: the browser, devtools,
and requests to `chat-ui`. It assumes the participant holds neither the agent key (with which they can call the
agent directly, on port 8100) nor root on the VM (with which they can edit any file, Open WebUI's database
included). A run sent straight to the agent is outside the chat, so it is not journaled; the agent's run log
(`runs.jsonl`) stays its only record, as today. The sandbox shares the `tools` network with the agent, so the
key alone closes that path: decision 17 checks that the sandbox never holds it.

## Decisions taken

| # | Decision | Section | Acceptance check |
|---|---|---|---|
| 1 | `chat-ui` owns the history; the agent is unchanged and stateless, and still trusts the history it is sent, which through the chat now comes only from the journal | [Approach](#1-approach) | `npm test` (recorder, with `lib/test-agent.ts` recording the input it receives): for a client history carrying each of a fabricated assistant turn, a fabricated tool call and result, a deleted middle turn, an edited reply, an edited tool result, a forged `spe-compaction-` marker and a client system message, the agent receives exactly the journal's path plus the new user message; no file under `platform/agui/pydantic-ai-agent/` changes |
| 2 | Per run, the **anchor** is the latest message of the client's history whose id the journal holds; the run's **new messages** are the user messages after the anchor whose ids the journal does not hold; everything else that differs from the journal's path to the anchor is **ignored content**, kind `fabricated` (unknown id), `edited` (known id, different role, content, tool calls or tool call id), `deleted` (on the journal's path, missing from the client) or `system` (a client system message) | [The run route](#2-the-run-route) | `npm test` (anchor): one case per kind, each recorded with the client's message in full; a session's first run has no anchor; **no false alarm**: a history the browser itself sent after real runs (CopilotKit's message shape, through the runtime route, with `fake_agent.py` in the built-server check) classifies nothing as ignored, over three runs including one with tool calls and one failed run |
| 3 | A run with no new user message, or with a `runId` the journal already holds, is refused; a refused run whose request passed the id, deleted and closing checks is still journaled (`run_start` then `run_end` `refused`), so what it carried is recorded; a duplicate `runId` is refused without a line | [The run route](#2-the-run-route) | `npm test`: a request carrying only a fabricated assistant turn gives `RUN_ERROR`, the agent is not called, and the journal holds `run_start` with that turn as `fabricated` and `run_end` `refused`; a reused `runId` gives `RUN_ERROR` and no new line |
| 4 | `run_start` (run id, anchor, new messages, ignored content, the request's other client-controlled fields: `tools`, `context`, `state`, `forwardedProps`) is written and fsynced **before** the agent is called; if it cannot be written the run is refused with "this session could not be saved" and the agent is not called | [The journal](#3-the-journal) | `npm test`: the agent's first received byte comes after `run_start` is on disk (test agent reads the file when called); with the sessions directory read-only the run gets `RUN_ERROR` with that message and the test agent records no call |
| 5 | The agent is sent the journal's path from the root to the anchor, then the new messages; `threadId` is the session id, `runId` the request's, the other fields forwarded as sent; the agent key is added by `chat-ui` as today | [The run route](#2-the-run-route) | Covered by decision 1's check; plus, in the built-server check against `fake_agent.py` scripted to echo the roles and ids it received, a `curl` to `chat-ui` carrying a fabricated assistant turn gets an answer that does not list it (the **feasibility check**: if CopilotKit's runtime cannot replace `messages`, the work stops for a new decision, see *Early output*) |
| 6 | When a run has ignored content, `chat-ui` first sends the browser a `MESSAGES_SNAPSHOT` of the history the agent is sent, so the browser shows what the model sees; without ignored content, nothing is added to the stream | [The run route](#2-the-run-route) | `npm test`: the stream to the client starts with a snapshot equal to the agent's input messages when content was ignored, and has none otherwise; Playwright against `fake_agent.py`: after a devtools edit of an earlier reply and a new message, the page shows the original reply |
| 7 | Every AG-UI event the agent sends is appended as it arrives; the journal is fsynced at `run_start`, at `run_end`, and at most one second apart in between; `run_end` holds the status (`completed`, `failed`, `cancelled`, `aborted`, `refused`) and the error message | [The journal](#3-the-journal) | `npm test`: a completed, a failed, a stopped (both abort shapes the recorder handles today) and a refused run each end with the matching `run_end`; with `fsync` counted and a fake clock, a run of 1000 events arriving within one second fsyncs at most three times (`run_start`, one interval, `run_end`) |
| 8 | An append that fails mid-run aborts the agent request and ends the run with `RUN_ERROR` "this session could not be saved" (`run_end` `aborted` if it can still be written); the `spe.session_save_failed` warning goes; a run with no `run_end` (a crash) is read as `incomplete`, its events kept | [The journal](#3-the-journal) | `npm test`: an append made to fail after five events aborts the test agent's request and gives that error; a journal cut after a run's third event rebuilds with that run `incomplete` and the text received so far; `grep -r session_save_failed platform/agui/copilotkit-chat` finds nothing |
| 9 | Runs on one session may overlap; one queue per session serialises appends; two runs from one anchor become sibling branches; the session's **tip** is the last message of the run whose `run_end` (or, if incomplete, last event) came last; the "already running" refusal goes | [Concurrency and branches](#4-concurrency-and-branches) | `npm test`: two runs started from the same anchor, the first ending last, both complete; the rebuild has two branches under the anchor and the tip is the first run's last message; their lines interleave and each line names its run |
| 10 | The journal is `/data/sessions/<uuid>.jsonl` on the `chat-sessions` volume, one JSON object per line (`created`, `run_start`, `event`, `run_end`, `meta`), append-only: no route ever rewrites or truncates it; session ids stay canonical UUIDs | [The journal](#3-the-journal) | `npm test`: after a session's runs, a rename, a tag, a hide and a delete, every earlier line is byte-identical and each operation added lines only; ids like `../x` are refused as today |
| 11 | Messages are rebuilt from the journal by applying each run's events to its anchor's path with `@ag-ui/client`'s own event handling (the code the browser runs); every message gets a `parentId`, derived from the run structure, not stored | [Rebuilding the conversation](#5-rebuilding-the-conversation) | `npm test` and the built-server check: for runs with text, tool calls and results, a compaction marker and an error, the rebuilt branch equals the messages the browser held at the run's end |
| 12 | The session list is served from an index in memory, built at startup with one pass over the journals and updated on every append; no index file | [Sessions API and restore](#6-sessions-api-and-restore) | `npm test`: the list after a restart equals the list before it; a rename shows in the list without rereading the file (the read is counted) |
| 13 | The session API keeps its routes and answer shapes for the browser; `GET /api/sessions/{id}` returns the tip's branch as `messages`; `PATCH` and `DELETE` append a `meta` line; no route changes message content; delete stays soft | [Sessions API and restore](#6-sessions-api-and-restore) | `npm test` (`api`): the existing answer-shape tests pass unchanged; a `PATCH` adds exactly one `meta` line; restore in Playwright reopens a session on its tip's branch |
| 14 | Session files in the earlier JSON format (`<uuid>.json`) are neither read nor migrated | [The journal](#3-the-journal) | `npm test`: a directory holding a `<uuid>.json` file lists no session for it and starts without error |
| 15 | The archive copies every journal raw (hidden and deleted included) and exports each as an **Open WebUI chat** in an Open WebUI-shaped bundle, written by an exporter in the `chat-ui` image that uses decision 11's rebuild; `write_run.py` renders the bundle as it renders an Open WebUI run; `write_agui_run.py` and its session format go | [Export and archive](#7-export-and-archive) | `pytest platform/dev/tests` with fixture journals: the exporter's bundle has, per session, a `history` tree whose `currentId` is the tip, one assistant message per run with `output` items in event order (`message`, `function_call`, `function_call_output`, `reasoning`) and the `spe_` fields below; `write_run.py` renders it into `index.md` and `chats/NN-*.md`; the archive tree holds `agui-journals/<uuid>.jsonl` and `agent-runs.jsonl` |
| 16 | `write_run.py` also renders the three things only the AG-UI record has: a run's status when it is not `completed`, its ignored content as a block "sent by the client, not used" with its kind and the content fenced, and a compaction marker as a "Compacted" section; Open WebUI runs render as before | [Export and archive](#7-export-and-archive) | `pytest`: a fixture with a fabricated assistant turn renders the block between the turns it was sent with, fenced with a fence longer than any backtick run inside; a marker renders as the Compacted section; an existing Open WebUI fixture renders byte-identically to before |
| 17 | Boundary: the agent key is never in the sandbox's environment nor in `terminal.env` | [Boundary](#8-boundary) | `verify.yml` on an `agui` instance: a new check in `roles/agui/tasks/checks.yml` that neither `docker inspect` of the sandbox's environment nor `terminal.env` contains the agent key's value |
| 18 | The threat catalog gains an entry for history fabricated through the client (fabricated or edited turns, tool results or markers claiming to be the agent's or the environment's words), with this design as its mitigation for the chat path | [Boundary](#8-boundary) | `uv run --with pyyaml --with python-frontmatter python validate.py` passes with the new `threats/TM-007-*.md` |

## Early output

Two samples, the first one before anything else is built. **First, the feasibility check** (decision 5): the
built server with `fake_agent.py`, a `curl` request to `chat-ui` carrying a fabricated assistant turn and a forged
`spe-compaction-` marker, the agent's echo of what it received, and the session's journal lines, pasted into
the first slice's handoff. If CopilotKit's runtime will not let `chat-ui` replace the history it forwards, the
user decides again whether the agent should own the history instead. **Second, the rendered archive chat** of
that session (`chats/01-*.md`) and of one normal session with tool calls: the user reads whether the ignored
content and the run statuses are clear to someone analysing a run, and whether the browser should also show
the ignored content (decision 6 only shows what the model saw). Either sample can change decisions 2, 6 and 16
while they are still cheap to change.

## Glossary

| Term | Meaning |
|---|---|
| Journal | A session's append-only record, `/data/sessions/<uuid>.jsonl` |
| Run | One request to `chat-ui`'s run route and the agent run it starts; `run_start` to `run_end` in the journal |
| Path | The chain of messages from the root to a message, following `parentId` |
| Anchor | The message a run continues from: the latest client message whose id the journal holds |
| New messages | The user messages after the anchor that the journal does not hold; the only part of a client's history that reaches the agent |
| Ignored content | Whatever else in the client's history differs from the journal's path, recorded with its kind |
| Branch | A path ending at a message with no children; runs from one anchor make sibling branches |
| Tip | The message the chat reopens on: the last message of the run that ended last |

## 1. Approach

Open WebUI's backend loads the stored chat and sends the model that, not the history in the completion request
(`load_messages_from_db` in v0.11.3's `utils/middleware.py`). When it fronts an external agent, the agent is
stateless and the backend owns the history. `chat-ui` is already a backend in that sense: its server route adds
the agent key and records the session. So it takes the same place, and the agent stays stateless:

- the record does not depend on the system under evaluation, which an infrastructure team may replace with
  another AG-UI agent;
- tools send history straight to the agent as before (promptfoo does), so the same attack can be run against
  the agent alone (it trusts a fabricated history) and through `chat-ui` (it does not), as a baseline and a
  mitigated variant of one experiment;
- the agent's compaction needs no change: it still trusts the marker it is sent, and through the chat a marker
  can now only come from the journal, that is from the agent itself.

Unlike Open WebUI, nothing edits the stored copy: there is no route that changes a message, so an edit through
the chat is always a new branch or ignored content, never an overwrite.

## 2. The run route

The hook is the recorder middleware `chat-ui` already installs on its `HttpAgent` (`lib/recorder.ts`,
`run(input, next)`), which sees `input.messages` before the request is sent. Per run, after today's checks
(valid id, not deleted, not closing):

1. Load the session from the index or journal. Compute the **anchor** and the **new messages** (decision 2),
   and compare the client's history with the journal's path to the anchor:
   - a client message with an id the journal does not hold, other than a new message: `fabricated`; this
     includes every message after the anchor that is not a user message, and every forged marker;
   - a client message with a known id whose role, content, tool calls or tool call id differ: `edited`;
     other fields CopilotKit may add are not compared;
   - a message on the journal's path missing from the client: `deleted`;
   - a client system message: `system` (the agent replaces it anyway; recorded so it is not mistaken for one
     that reached the model).
2. Refuse a run with no new user message or a reused `runId` (decision 3).
3. Write `run_start` (decision 4).
4. Replace `messages` with the path plus the new messages and call `next` (decision 5). If anything was
   ignored, emit `MESSAGES_SNAPSHOT` to the client first (decision 6).
5. Append each event; write `run_end` from the terminal event, as the recorder maps statuses today
   (`RUN_FINISHED` → `completed`, `RUN_ERROR` with code `abort` or a raw `AbortError` → `cancelled`, other errors
   → `failed`).

Content is compared as the canonical JSON of the compared fields, so key order and absent-versus-empty fields
do not count as edits; the no-false-alarm check in decision 2 pins this against what CopilotKit really sends.

## 3. The journal

`/data/sessions/<uuid>.jsonl`, one object per line, each with `type` and `at` (ISO 8601 UTC):

| `type` | Fields |
|---|---|
| `created` | `version: 1`, `id`; first line, written with the first `run_start` |
| `run_start` | `run_id`, `anchor` (message id or null), `messages` (the new messages), `ignored` (list of `{kind, message}`; for `deleted`, the id), `request` (`tools`, `context`, `state`, `forwardedProps` as sent), `source: "chat"` |
| `event` | `run_id`, `event` (the AG-UI event as received) |
| `run_end` | `run_id`, `status`, `error` (message or null) |
| `meta` | any of `title`, `tags`, `pinned`, `hidden`, `deleted_at`, as the session API sets them |

The title rule stays: the first user message cut to 60 characters until a `meta` sets one. A run's `run_start`
is fsynced before the agent is called; events are fsynced at most a second apart, and `run_end` at once, so a
hard kill loses at most a second of one run. A run without `run_end` is `incomplete`. Write failures end the run
(decision 8): a record that silently misses events would be worse than a failed run. The journal and the
archive hold no request headers and no configuration, so never the agent key; message content is stored
unchanged.

## 4. Concurrency and branches

Open WebUI allows a second message while a reply is streaming; so does this design. Each line names its run, and
appends to one session go through one queue, so lines never interleave within a line. Two runs from the same
anchor each chain their messages under it: siblings. A browser that keeps sending its own history continues from
its own latest message, so concurrent runs from two tabs show up as two branches rather than one corrupted
history. The chat reopens on the tip; navigating between branches in the chat is out of scope (the archive keeps
them all).

## 5. Rebuilding the conversation

For each run in journal order: take the path to its anchor, append its new messages, and apply its `event` lines
with `@ag-ui/client`'s event application, as the browser does. The messages the run added are, in order of first
appearance, chained by `parentId`: the first new message's parent is the anchor, every later message's parent
is the one before it. A `MESSAGES_SNAPSHOT` the agent itself sends is applied like any event; the one
`chat-ui` sends to the browser (decision 6) is not journaled, since it is derived. The rebuild lives in one module
used by the run route, the session API and the exporter, so the chat and the archive cannot disagree.

## 6. Sessions API and restore

The browser's side does not change: `GET /api/sessions` (list, newest first, capped at 1000), `GET`, `PATCH`,
`DELETE /api/sessions/{id}`, the same fields and validation. The list comes from an index in memory: one pass
over the journals at startup (each file's `created`, latest `meta` values, first user message and last line's
time), updated by every append. `GET` one rebuilds the session and returns the tip's branch as `messages`, which
the page passes to `setMessages()` as today. `PATCH` and `DELETE` append `meta`. Deleted sessions stay out of
every answer and are refused for new runs.

## 7. Export and archive

The archive's barrier stays (stop `chat-ui`, then the agent, then copy). It copies each journal raw to
`agui-journals/` and the agent's `runs.jsonl` to `agent-runs.jsonl`, then runs the exporter from the `chat-ui`
image in a one-off container over the copied journals. The exporter writes the bundle `write_run.py` already
reads for Open WebUI (`{chats: [...], tags: [...], notes: []}`), one chat per session:

- `title`, `created_at`, `updated_at`, `archived` (the session is hidden), `meta.tags`, and
  `meta.spe_deleted_at` for a deleted session;
- `chat.history.messages`: every message of every branch, keyed by id, with `parentId` and `childrenIds`;
  `chat.history.currentId`: the tip;
- a user message as Open WebUI's: `role`, `content`;
- **one assistant message per run**, parent the run's last new user message, with `output` items in the order
  their first event arrived, in v0.11.3's shapes (`utils/middleware.py`, `utils/ask_user.py`): a text message as
  `{type: "message", id, role: "assistant", content: [{type: "output_text", text}]}`, a tool call as
  `{type: "function_call", id, call_id, name, arguments}` (`arguments` a JSON string), a tool result as
  `{type: "function_call_output", id, call_id, output: [{type: "input_text", text}]}`, reasoning as
  `{type: "reasoning", id, content}`, each with `status: "completed"`; a compaction marker as a `message` item
  keeping its id; `content` is the run's text joined. These are the items Open WebUI itself replays to a model
  (`MESSAGE_REPLAY_KEYS`, `process_messages_with_output`), so the export is a chat Open WebUI could continue;
- `spe_run` on that assistant message (`run_id`, `status`, `started_at`, `ended_at`), and `spe_ignored` (the
  run's ignored content) on it too, so a refused run still has a message to carry what it was sent.

`write_run.py` renders it like an Open WebUI run (`index.md`, `chats/NN-<slug>.md` and `.json`), the active
branch along `currentId`, plus decision 16's three additions. Fields starting with `spe_` are ours; Open WebUI
itself never writes them, so its own runs render as before.

## 8. Boundary

The design closes the chat path. Two paths stay outside it and are stated, not solved:

- **The agent key.** Whoever holds it calls the agent directly; the agent trusts any history and only its run
  log records the run. `chat-ui` holds the key in `chat-ui.env`, the agent in `agent.env`; the controller keeps a
  copy in its output directory. The sandbox shares the agent's `tools` network, so its environment must never
  hold the key (decision 17).
- **Root on the VM.** Whoever has it can edit any record on the VM, Open WebUI's database and these journals
  alike. Making records tamper-proof against root needs them shipped off the VM as they are written.

The threat entry (decision 18) describes the attack independently of the frontend: the injected content claims
to be the agent's own words or the environment's (a tool result), which makes it stronger than pasted text
(TM-005). Open WebUI's request path is closed the same way, but its stored chat is editable by design (its
message edit and history merge endpoints), so there the entry's mitigation is partial.

## Out of scope

- Navigating branches in the chat (CopilotKit's page passes no edit or regenerate handlers).
- Recording runs sent straight to the agent beyond its run log.
- Participants' root access on the VM, and records shipped off the VM.
- A promptfoo target that runs through `chat-ui` (the mitigated variant of section 1's experiment).
- Recording edits made in Open WebUI (its event webhook or audit log).
- A run with no new user message (a manual "compact", a regenerate): refused by decision 3 until one is needed.

## Inputs for the plan

- Build decision 5's feasibility check first, in the first slice, before the session API or the archive move.
- One rebuild module (decision 11) shared by the route, the API and the exporter; the exporter runs in the
  `chat-ui` image, so the archive needs no Node on the controller.
- What the agent does with `context`, `state` and `forwardedProps` is not checked here: the plan reads the
  agent's adapter and records the answer, since `run_start` stores them either way.
- The compaction marker's archive rendering moves to `write_run.py` (decision 16) wherever it lives when the
  plan starts.
- The chat's README (*Sessions*), the getting-started guide and the frontend design spec (§6) describe the
  storage: the slice that changes it rewrites them.
- `@ag-ui/client`'s event application is used as a library on the server; check that its entry point works in
  the Node runtime the image uses, and pin the behaviour with decision 11's test.

## Clarifications

None yet.
