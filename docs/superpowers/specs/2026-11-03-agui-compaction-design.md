# AG-UI compaction — design

**Status:** proposed, PR #15. **Latest clarification:** none.
Read against this repo at `4a59a6c` (`main`), with `pydantic-ai-slim` 2.56.0, `ag-ui-protocol` 0.1.22,
`@ag-ui/core`/`@ag-ui/client` 1.0.2 and CopilotKit 1.79.0 as pinned there.

**Who reads it:** whoever plans or implements compaction in the AG-UI agent
(`platform/agui/pydantic-ai-agent/`), its rendering in the chat UI (`platform/agui/copilotkit-chat/`) and the
archive (`roles/run_archive`), and whoever analyses archived AG-UI runs and needs to know what the model saw.

**Problem.** Nothing in the AG-UI stack handles the model's context limit. The CopilotKit chat sends the whole
history with every run; the agent passes it to the model unchanged (no history processor in
`src/spe_agent/`). Each tool result is cut at `tools.max_output_bytes` (16 KB, `spe_agent_max_output_bytes`;
not 1 MB as the handoff said), but one run may make 50 requests and 100 tool calls, so a single run can add
about 1.6 MB, and a session grows across runs without bound. When a request no longer fits, the provider's
error becomes `RUN_ERROR` in the red bar, and **every later message in that session fails the same way**,
because the history only grows. `limits.total_tokens_limit` does not help: it caps a run's summed spend, not the
size of one request.

**Decision.** The **agent** compacts. A pydantic-ai capability runs before every model request. When the
history the model would be sent is estimated past a share of the model's context window, or when the
provider has just rejected a request as too long, it asks the same model for a summary of the history so far.
The model is then sent the system prompt, the summary and whatever came after it. The summary goes into
the run's AG-UI stream as one **activity message** (`activityType: "compaction"`, pydantic-ai's own
`CompactionPart` carrier), so the chat keeps it in its history. The session record, which still holds every
original message, therefore holds the summary too, at the point where it was made. On later runs the agent
cuts the history at the latest compaction. The chat shows a divider with the summary, and the archive
renders it. The browser always keeps and sends the full history; only what the model sees shrinks.

## Decisions taken

| # | Decision | Section | Acceptance check |
|---|---|---|---|
| 1 | Compaction lives in the agent, as a capability on the `spe-agent` `Agent`, for every provider; not in the chat UI, not provider-native | [Approach](#1-approach) | `pytest` (agent): with a `FunctionModel`, a history past the trigger leads to one summary request and then a model request that holds the system prompt, the summary and only the messages after the cut; the same suite passes for `provider: anthropic` and `openai_compatible` configs |
| 2 | Proactive trigger: before each model request, estimated tokens of what would be sent ≥ `trigger_ratio` × `context_window_tokens`; off while `context_window_tokens` is unset | [Trigger](#2-trigger) | `pytest`: estimates just under and just over the trigger compact 0 and 1 times; with `context_window_tokens: null` a large history is sent uncompacted; inside one run, tool results that push the history over the trigger compact before the next request, not only at the run's start |
| 3 | Reactive trigger: a request the provider rejects as too long (a fixed list of overflow errors) is compacted and retried once, whether or not a window is configured | [Trigger](#2-trigger) | `pytest`: a `FunctionModel` raising each listed overflow error (Anthropic, OpenAI, vLLM wording) once, then answering, gives one compaction and a completed run; an unlisted 400 is not retried and reaches `RUN_ERROR` as today; overflow again after the retry gives `RUN_ERROR` with the message of decision 6 |
| 4 | The summary replaces everything before it: the model is sent the system prompt, then one user message holding the framed summary, then the messages after the latest compaction marker, unchanged; the summary prompt asks for the latest user request verbatim and the state of the task | [What the model sees](#3-what-the-model-sees) | `pytest`: requests after a compaction, in the same run and in a later run rebuilt from AG-UI messages, have exactly that shape; the system prompt is present in both; a marker from another producer (`provider_name` not `spe-agent`) is ignored |
| 5 | The summary request uses the same model, no tools, a fixed prompt kept in the package, a transcript with each tool result cut to 2000 characters, at most `summary_max_tokens` of output; its usage counts towards the run's usage and limits | [The summary request](#4-the-summary-request) | `pytest`: the summary request carries no tool definitions, the cut tool results and the package prompt; `result.usage` after a compacting run includes it; a run at `request_limit` - 1 that needs a compaction ends with the usage-limit error, as any extra request would |
| 6 | At most one compaction per model request and three per run; past that the run fails with "The conversation is still too long after compacting it. Start a new chat." | [Trigger](#2-trigger) | `pytest`: a summary that is itself past the trigger does not compact again for the same request; a fourth compaction in one run gives `RUN_ERROR` with that message |
| 7 | The marker is an AG-UI `ACTIVITY_SNAPSHOT` (`activityType: "compaction"`, content as pydantic-ai's `compaction_payload` of a `CompactionPart` with `provider_name: "spe-agent"`), emitted before the events of the model response it preceded, so it is stored as an `ActivityMessage` in the chat's history and read back as a `CompactionPart` | [The marker](#5-the-marker) | `pytest` (agent): the event stream of a compacting run has the snapshot right before that response's first event; feeding the run's messages, including the `ActivityMessage`, back in as a new run's input cuts there. `npm test` (chat): the recorder, given a scripted stream with the snapshot, stores the `ActivityMessage` in `messages` in order; reopening the session and running again sends it back to the agent (a test of CopilotKit's runtime path, see *Inputs for the plan*) |
| 8 | The chat renders a compaction as a divider ("Earlier conversation compacted") with the summary in a collapsed `<details>`, as text; nothing else in the chat changes | [The chat](#6-the-chat) | Playwright against `fake_agent.py` scripted to emit a compaction: the divider appears in place, live and after a reload; expanding shows the summary as literal text (a summary holding `<img src=x onerror=…>` shows the markup); screenshots light and dark in the slice's handoff |
| 9 | The session record keeps every message the browser sent plus the `ActivityMessage`; schema `version` stays 1; title, runs and the session API are unchanged | [Session record and archive](#7-session-record-and-archive) | `npm test`: a recorded compacting run validates against the existing schema; the auto title is still the first user message |
| 10 | The archive renders a compaction as a marked section with the fenced summary, between the messages it sits between; all original messages are still rendered | [Session record and archive](#7-session-record-and-archive) | `pytest platform/dev/tests -k agui_run`: a fixture session with a compaction renders every original message, then the "Compacted" section with the summary in a fence longer than any backtick run inside it; the index gains a `compactions` count per session |
| 11 | The run log records each compaction: trigger (`threshold` or `overflow`), estimated tokens before, messages cut, the summary text and the summary request's usage; redacted like every record | [Run log](#8-run-log) | `pytest`: a compacting run's record has a `compactions` list with those fields; a summary containing the sandbox key is written redacted |
| 12 | Configuration: `compaction.enabled` (default true), `compaction.context_window_tokens` (default null), `compaction.trigger_ratio` (default 0.8, in (0, 1)), `compaction.summary_max_tokens` (default 4096), rendered by Ansible from `spe_agent_compaction_*` variables; the dev VM's instance and the de.NBI testbed presets set the window | [Configuration](#9-configuration) | `pytest` (config): defaults, a ratio of 0 or 1 or an unknown key refused; with `enabled: false` neither trigger acts; `ansible-playbook --syntax-check`; `verify.yml` on the dev VM shows the rendered values |
| 13 | A session that already fails with an overflow recovers: its next message compacts (decision 3) and the run completes | [Trigger](#2-trigger) | On the dev VM (Haiku, approved): a session pushed past a small configured window (`context_window_tokens: 20000`) by tool output keeps working, the divider shows, and the next request's input tokens in the run log are below the window; the same session with compaction disabled fails with the provider's error |

## Early output

Slice 1 is the agent alone, tested with `FunctionModel` (no model calls): decisions 1 to 7 and 11. The first
thing the user sees is in slice 2: **a dev VM session with `context_window_tokens: 20000`, run on Haiku
until it compacts**, the divider in the chat, and the session's archived `chats/NN-*.md`. The user looks at
the summary's quality and at how the divider and the archive section read. Either can change the summary
prompt, the trigger ratio or the rendering before the configuration and the de.NBI presets are done.

## Glossary

| Term | Meaning |
|---|---|
| window | the model's context window in tokens (`context_window_tokens`) |
| compaction | replacing, for the model, the history up to a point with a summary of it |
| marker | the `ActivityMessage` (in AG-UI) or `CompactionPart` (in pydantic-ai) that holds a summary; the cut point |
| our marker | a marker with `provider_name: "spe-agent"`; markers from any other producer are ignored |
| what is sent | the messages of one model request after the cut: system prompt, framed summary, the rest |

## 1. Approach

Three places could compact. **The chat UI** (the runtime route rewrites the history before forwarding it) would
need the LLM key, which the chat UI must never hold (chat sessions spec, §5), and could not act inside a run,
where one run can outgrow the window by itself. **Provider-native compaction** (pydantic-ai's
`AnthropicCompaction` and `OpenAICompaction`) covers Anthropic and the OpenAI Responses API only; the
participants' de.NBI setup is `openai_compatible` (vLLM, chat completions) and would get nothing. Two
mechanisms for two providers would also mean two behaviours to evaluate. **The agent**, as a pydantic-ai
capability (`before_model_request` / `wrap_model_request` and `on_model_request_error`), sees every request,
inside a run too, uses the model it already has, and works the same for every provider and every AG-UI client
(the promptfoo provider included). It is chosen.

Dropping old messages or old tool results without a summary was also considered: no extra request, but the
model silently loses what the participant asked and what it found. It stays a possible cheaper first stage
(*Out of scope*).

The new code is one module, `src/spe_agent/compaction.py`: estimate, overflow detection, summary request,
building what is sent, and the capability. `agent.py` adds the capability when `compaction.enabled`; `app.py`
forwards the marker events (§5) and gives the run log the compaction records (§8).

## 2. Trigger

Before each model request the capability estimates what is sent:

- the latest `ModelResponse` of this run that has usage: its input tokens plus its output tokens, plus the
  characters of every message after it divided by 3;
- with no such response (a run's first request), the characters of what is sent, the system prompt and the
  tool definitions divided by 3.

Three characters a token over-estimates English and JSON for the tokenizers in use, which errs towards
compacting early. **Proactive:** when `context_window_tokens` is set and the estimate is at least
`trigger_ratio` × `context_window_tokens`, compact before sending. **Reactive:** when the provider rejects a
request with an overflow error, compact and send it again, once. The overflow errors are a fixed list in
`compaction.py`, each with a test: `ModelHTTPError` with status 400 or 413 whose body contains
`prompt is too long` (Anthropic), `context_length_exceeded` or `maximum context length` (OpenAI and vLLM),
`input is too long` or `too many tokens`. Any other error passes through as today. The reactive path is what
makes a session that already overflows recover (decision 13), and it covers an unset or wrong window.

**Limits.** A model request is compacted at most once: if what is sent after compacting is still past the
trigger, it is sent anyway, and an overflow at that point fails the run. A run compacts at most three
times; a fourth would fail the run with "The conversation is still too long after compacting it. Start a
new chat." These errors, like every `RUN_ERROR`, go through `Service.sanitize`.

## 3. What the model sees

Given the history (pydantic-ai messages, from AG-UI input plus this run), the capability finds **our latest
marker** and builds what is sent:

1. the system prompt parts, as today (the AG-UI adapter's `manage_system_prompt="server"` re-injects them; the
   capability keeps them in the first request whatever the cut);
2. one `UserPromptPart`: `"[Summary of the earlier conversation, written when it no longer fit the model's
   context]\n\n" + summary`;
3. every message after the marker, unchanged, so tool calls and their results stay paired: a cut is only made
   before a model request, never between a call and its result.

The marker itself is never sent to the provider. With no marker, the history is sent as today. Markers whose
`provider_name` is not `spe-agent` (one a provider made, or a client wrote) are ignored, as pydantic-ai's
own wire rule ignores markers from another provider.

**Making one.** To compact, the capability asks for a summary of everything that would be sent (§4), puts
our marker in the run's history in place of what it covers (`ctx.messages`, as pydantic-ai's
`ProcessHistory` does), and sends the request in the shape above. The summary therefore covers the
previous summary too, and the latest user request; the summary prompt asks for that request verbatim, the
task's state, what was found (paths, commands, results that matter) and what was about to be done.

**Trust.** A participant can edit the history the browser sends, a marker included. The agent already trusts
the whole history (chat sessions spec, §2, *What the record means*); a forged marker is one more way to
write that history, not a new boundary. The session record shows what the agent was sent, the run log what
it made.

## 4. The summary request

One request to the same `Model`, outside the agent's graph (`model.request`), with:

- a system prompt from `src/spe_agent/compaction_prompt.md`, shipped in the package, not configurable;
- one user message holding a plain-text transcript of what would be sent: user and assistant text in full,
  each tool call with its arguments, each tool result cut to its first and last 1000 characters with
  `[… N characters cut …]` between;
- no tool definitions; `max_tokens` = `summary_max_tokens`.

If the transcript itself is past the trigger, its oldest entries after the previous summary are left out,
oldest first, until it fits, and the transcript says how many were left out. With no window configured, a
summary request that the provider rejects as too long is retried once with the older half of those entries
left out the same way. Its usage is added to the run's
usage (`ctx.usage`), so `request_limit`, `total_tokens_limit` and the run log count it like any request. A
summary request that fails fails the run, with its error, as a model request would.

## 5. The marker

The capability puts the marker on a per-run queue in `RunDeps`. `Service._events`, which already rewrites
the stream (`RUN_ERROR` sanitising), yields every queued marker as an `ACTIVITY_SNAPSHOT` before the next
event it forwards, and before a terminal event. The next event after a compaction is the first event of the
response it preceded, so the snapshot lands just before it. If pydantic-ai's own event stream can carry it
(a `CustomEvent` whose payload is the `ActivitySnapshotEvent`, which `AGUIEventStream.handle_custom_event`
passes through), the plan may use that instead; the order is the contract, not the mechanism.

The snapshot: `messageId` a new UUID, `activityType: "compaction"`, `content` = pydantic-ai's
`compaction_payload(CompactionPart(content=summary, provider_name="spe-agent"))`, `replace: true`. The AG-UI
client turns it into an `ActivityMessage` in the thread's messages, so it is stored, shown and sent back. On
the next run, pydantic-ai's AG-UI adapter reads it back into a `CompactionPart` at the same position, which
§3 cuts at.

## 6. The chat

CopilotKit has no renderer for a `compaction` activity. The chat registers one: a full-width divider,
"Earlier conversation compacted", with a `<details>` whose summary line is "Summary the model continues
from" and whose body is the summary as React text (`white-space: pre-wrap`), in the chat's existing colours,
light and dark. Nothing else changes: the composer, the stop button, the red bar and the sidebar behave as
before; an overflow that compaction could not fix still shows in the red bar.

No manual "compact" action (*Out of scope*).

## 7. Session record and archive

How the chat sessions spec's constraints change:

- **§1, the record stores the full messages the browser sends**: unchanged. `messages` holds every original
  message plus one `ActivityMessage` per compaction, at the point it was made. It is still AG-UI `Message[]`,
  so `version` stays 1 and `agent.setMessages()` takes it as before. The record grows as it does today; the
  summary adds at most `summary_max_tokens` of text per compaction.
- **§2, the recorder writes what the run ends with**: unchanged code; what the run ends with now includes
  the `ActivityMessage`. The admission, finalisation and status rules are untouched.
- **§4, the archive renders every message**: still every message. `write_agui_run.py` renders an
  `ActivityMessage` with `activityType: "compaction"` as a section `## Compacted` with the line "From here the
  model saw this summary instead of the messages above." and the summary in a fence (decision 14 of the
  chat sessions spec). Other activity messages keep today's JSON rendering. `index.md` gains a `compactions`
  column.

## 8. Run log

Each run record gains `compactions`: a list, empty when none, of
`{trigger: "threshold" | "overflow", estimated_tokens, messages_cut, summary, usage}`. It is redacted like the
rest of the record. With it the run log alone says what the model saw in each run, which the canary
evaluation needs: a compaction changes the context an injected instruction or a canary sits in (biohackathon
0013).

## 9. Configuration

`agent.yaml` gains:

```yaml
compaction:
  enabled: true
  context_window_tokens: null   # the model's window; null: only the reactive trigger
  trigger_ratio: 0.8
  summary_max_tokens: 4096
```

Ansible renders it from `spe_agent_compaction_enabled`, `spe_agent_context_window_tokens`,
`spe_agent_compaction_trigger_ratio` and `spe_agent_compaction_summary_max_tokens` (`group_vars/all.yml`,
`roles/agui/tasks/main.yml`). The de.NBI testbed presets (`platform/coder/template/testbeds/*.yml`) set the
window to the served model's `max_model_len`; `docs/getting-started.md` says how to set it for another model;
the dev VM's private instance file sets Haiku's. `platform/ansible/README.md` and the agent's README describe
the block.

## Out of scope

- A **manual "compact" action** in the chat (as `/compact` in Claude Code). It needs a run with no new user
  message, which the recorder's title rule and the agent's run input do not have today. To `BACKLOG.md`.
- **Dropping or shortening old tool results** before summarising (Anthropic's context editing), as a cheaper
  first stage. To `BACKLOG.md`, to revisit if summary requests prove costly.
- **Reading the window from the provider** (vLLM's `/v1/models` reports `max_model_len`). Configuration is
  enough while presets are few.
- **Provider-native compaction**, as an option beside ours (§1).
- The **Open WebUI** frontend, which has its own context handling.

## Inputs for the plan

- **First task: pin the round trip.** Before building on it, a test that an `ACTIVITY_SNAPSHOT` from the
  agent survives CopilotKit 1.79's path both ways: applied to the agent's messages in the browser and in the
  recorder's `runNextWithState`, kept by `setMessages()`, and sent back by the runtime to the agent on the next
  run (the runtime may drop roles it does not know). If it does not survive, the fallback is an assistant
  message with id prefix `spe-compaction-` and the summary as text, which the agent's AG-UI input conversion
  maps to our marker; record that as a ruling and a clarification here.
- Check where the capability must sit relative to the adapter's `ReinjectSystemPrompt` so the system prompt
  is in every request after a cut (decision 4).
- Check that `ag_ui_version` as the adapter resolves it allows activity events (`ACTIVITY_EVENTS_VERSION`) for
  the input CopilotKit sends, or §5's `Service` emission does not depend on it.
- Slices, in order: (1) agent: `compaction.py`, the capability, configuration, events, run log, with
  `FunctionModel` tests; (2) chat renderer and recorder test, `fake_agent.py` compaction script, archive
  rendering, then the early output on the dev VM; (3) Ansible variables, presets, docs, and decision 13's
  model-backed check.
- Paid runs: decision 13 and the early output use Haiku on the dev VM, approved by the user for this work
  (2026-11-02). No de.NBI runs are needed; the preset value is read from the vLLM server's `/v1/models`.

## Clarifications

None yet.
