# AG-UI conversation record: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` (`AGENTS.md`,
> *Working Conventions*) to implement one slice per session and PR. Steps use checkbox (`- [ ]`) syntax.

**Goal:** `chat-ui` owns each session's history as an append-only journal: from every run request it takes only
the new user message, sends the agent the history from its journal, and records whatever else the client sent as
ignored content; the archive copies the journals raw and exports each as an Open WebUI chat that `write_run.py`
renders.

**Spec:** the living AG-UI spec [`docs/specs/2026-10-15-agui-frontend-design/`](../../../specs/2026-10-15-agui-frontend-design/README.md):
§13 (the record), §14 (the archive), §6 (sessions, as restated for the record), decisions 1–30 in its README,
*Early output*, and [`inputs-for-plan.md`](../../../specs/2026-10-15-agui-frontend-design/inputs-for-plan.md).
Latest clarification when this plan was written: 2. Each slice file names the decisions it implements.

**Architecture.** Four new modules in `platform/agui/copilotkit-chat/lib/`, each with one job, and two
rewritten ones:

- `journal.ts`: the line format, parsing a journal (a torn line skipped), and `JournalWriter`, the only code that
  appends to a journal (the `\n` repair, the fsync policy).
- `rebuild.ts`: a journal's lines → a `Conversation` (every message with its `parentId`, the runs, the tip),
  applying each run's events with `@ag-ui/client`'s `defaultApplyEvents`, the code the browser runs. One module
  for the run route, the session API and the exporter (decision 11).
- `anchor.ts`: a client history against a `Conversation` → anchor, new messages, ignored content (decision 2).
- `export.ts`: a `Conversation` → an Open WebUI chat (§14), run in the `chat-ui` image by
  `scripts/export-journals.ts`.
- `sessions.ts` (rewritten): the session index on `globalThis`, the per-session append queue, metadata as `meta`
  lines; no `<uuid>.json`.
- `recorder.ts` (rewritten): the run route's middleware on the journal: admit, classify, `run_start`, replace
  `messages`, journal every event, `run_end`.

The archive's writer `write_run.py` learns the three AG-UI additions (status, ignored content, compaction) and
`write_agui_run.py` goes. The agent (`platform/agui/pydantic-ai-agent/`) does not change.

**Tech stack:** Next.js 16.4.1, CopilotKit 1.79.0 (v2 runtime), `@ag-ui/client` 1.0.2, rxjs 7.8.1, Node 24
`node --test` with type stripping (chat); Python standard library (`write_run.py`, `platform/dev/tests`);
Playwright (Python, `platform/dev/e2e/`); Ansible from the system package.

## Order against the compaction track

The compaction track's slice 2/3 (#18, `impl/agui-compaction-2-chat-archive`, draft when this plan was written)
touches files this plan rewrites: `lib/recorder.test.ts` (a recorder test that the session keeps the marker),
`files/write_agui_run.py` (`## Compacted`, a `Compactions` column), `platform/dev/fake_agent.py` and
`platform/dev/e2e/sessions.py`. Its slice 3/3 touches only Ansible variables for de.NBI and docs.

- **Slice 1 starts now**: it adds new files only and changes nothing #18 touches.
- **Slices 2–4 start from `main` after #18 has merged**, and do **not** wait for compaction 3/3: they share no
  file with it, so whichever merges second rebases. Slice 2's first step checks `gh pr view 18 --repo
  thodkatz/elixir-biohackathon-2026-test --json state` is `MERGED`; if not, the session ends blocked on it
  (`next-session.sh --end --blocked 18`), it does not start the slice.
- What #18 adds that the record replaces is carried over, not dropped: its `## Compacted` rendering and its
  `Compactions` column move into `write_run.py` (slice 2, task 3; inputs-for-plan, bullets 5 and 8); its recorder
  test that the record keeps the marker becomes a journal test (slice 3, task 2); its fake agent `compact`
  keyword stays.
- #18's clarification for the archive is #18's to move into the living spec's `clarifications.md` (its handoff
  `2026-11-03T1700Z-slice-2-task-4-step-4-retargeted.md`). A slice that adds a clarification takes the next free
  number in that file when it commits, not a number written here.

## Rulings

Each is *decision, why, cost if wrong*; a slice that departs from this plan adds one to its handoff and rewrites
the task text it changes.

1. **Slice 1 lands the pure modules unwired.** `journal.ts`, `rebuild.ts` and `anchor.ts` merge before anything
   uses them, so the feasibility check and the hardest logic are reviewed on their own and nothing #18 touches
   changes. *Cost if wrong:* a module shaped wrongly for its caller is reshaped in slice 3, at the price of one
   rewritten test file.
2. **The exporter ships before the route switches storage** (slice 2 before slice 3), so `main` never has
   journals that the archive cannot render: slice 3 switches the store, the route and the archive's export in one
   PR. *Cost if wrong:* slice 2's exporter is tested only on fixture journals until slice 3; slice 3's built-server
   sample is its first real input.
3. **The feasibility check is a runtime-level test plus the built-server sample.** Slice 1, task 1 pins, through
   `createCopilotRuntimeHandler` and a real `HttpAgent` (as the route builds it), that a middleware replacing
   `input.messages` decides what the agent receives; slice 3, task 5 produces the spec's sample (the built server,
   `curl`, `fake_agent.py`'s echo, the journal lines) once the journal is wired. If task 1's test fails, the work
   stops for the user's new decision (spec, *Early output*): the session comments on PR and ends blocked.
   *Cost if wrong:* none beyond the order; the sample the user reads is the same.
4. **`ignored` entries share one shape.** `run_start.ignored` is a list of `{kind, message}`; for `deleted`,
   `message` is the deleted message's id (a string), the literal reading of §13 *The journal*. *Cost if wrong:* a
   reader that expects an object for every kind needs one `typeof` check.
5. **What the agent does with `context`, `state`, `forwardedProps`:** nothing of its own. `app.py` hands the
   whole `RunAgentInput` to pydantic-ai's `AGUIAdapter` (`_Adapter(agent=…, run_input=…)`, `app.py:92-101,
   190-204`), after rewriting only compaction markers; `RunDeps` takes only `thread_id`. So `run_start.request`
   records them and the route forwards them unchanged (decision 5). Read 2026-11-03; *cost if wrong:* none for the
   record, which stores them either way (inputs-for-plan, bullet 4).

## Global Constraints

Every task's requirements include these.

- **Tests, before every commit**, the suites a slice touches (`AGENTS.md`, *Running things*):
  `(cd platform/agui/copilotkit-chat && npm ci && npm test && npm run build)`,
  `uv run --with pytest pytest platform/dev/tests -q`,
  `cd platform/ansible && ansible-playbook --syntax-check playbooks/create.yml playbooks/verify.yml playbooks/archive.yml playbooks/destroy.yml </dev/null`,
  `uv run --with pyyaml --with python-frontmatter python validate.py` (slice 4).
- **No new dependencies.** The chat uses `@ag-ui/client`, `@copilotkit/runtime`, `rxjs` and Node's standard
  library; Python stays standard library.
- **No file under `platform/agui/pydantic-ai-agent/` changes** (decision 1).
- **The journal is append-only**: no code path opens a journal for anything but appending (`fs.open(path, "a")`)
  or reading; nothing renames, truncates or rewrites one (decision 10). `JournalWriter` is the only writer.
- **Names fixed by the spec:** journal path `/data/sessions/<uuid>.jsonl` (`SPE_SESSIONS_DIR`, default
  `/data/sessions`); line types `created`, `run_start`, `event`, `run_end`, `meta`; statuses `completed`,
  `failed`, `cancelled`, `aborted`, `refused`, and `incomplete` for a run without `run_end` (never written);
  ignored kinds `fabricated`, `edited`, `deleted`, `system`; `source: "chat"`; `created.version: 1`; the refusal
  and failure messages `invalid session`, `this session was deleted`, `the chat UI is shutting down`,
  `this session could not be saved`; `globalThis` keys `Symbol.for("spe.sessions.queue")` and
  `Symbol.for("spe.sessions.index")`; archive paths `agui-journals/<uuid>.jsonl`, `agent-runs.jsonl`; bundle field
  `spe_archive_mode` `live` | `final`; chat fields `spe_run` (`run_id`, `status`, `started_at`, `ended_at`),
  `spe_ignored`, `meta.spe_deleted_at`; the block heading "sent by the client, not used".
- **Never stored:** request headers and the chat UI's configuration (the agent key) are never in a journal, a
  log line or the archive; message content is stored unchanged (decision 27). Log lines name ids, never content.
- **Model text is text:** React text in the sidebar; in the archive a fence one backtick longer than the longest
  backtick run inside (at least three), with `write_run.py`'s existing `fence()`.
- **No model calls, no cloud instances.** Every check uses `lib/test-agent.ts` or `platform/dev/fake_agent.py`.
  The dev VM's instance is redeployed in place with `create.yml` from the main checkout and
  `-e spe_agui_source_dir=<worktree>` (`AGENTS.md`, *Worktrees and deploying*); `destroy.yml` is run only against
  the dev VM's instance in slice 4, task 5, after asking the user (it is a destroy).
- **Upstream-clean:** code, READMEs, Ansible and `platform/` comments name nothing fork-only; the spec already
  lives in `docs/specs/` for that reason (`AGENTS.md`, *Overrides*).
- **Rulings:** a departure from this plan is recorded in the slice's handoff as *decision, why, cost if wrong*,
  and the same commit rewrites the plan task text (and, through a clarification, the spec text) it changes.

## Shared interfaces

Later slices use these names exactly. Paths are relative to `platform/agui/copilotkit-chat/`.

**`lib/journal.ts`** (slice 1, task 2)

```ts
import type { BaseEvent, Message } from "@ag-ui/client";

export type RunStatus = "completed" | "failed" | "cancelled" | "aborted" | "refused";
export type IgnoredKind = "fabricated" | "edited" | "deleted" | "system";
export type Ignored =
  | { kind: "fabricated" | "edited" | "system"; message: Message }
  | { kind: "deleted"; message: string };                 // the deleted message's id (ruling 4)
export type RequestFields = { tools: unknown[]; context: unknown[]; state: unknown; forwardedProps: unknown };
export type MetaFields = { title?: string; tags?: string[]; pinned?: boolean; hidden?: boolean; deleted_at?: string };

export type CreatedLine = { type: "created"; at: string; version: 1; id: string };
export type RunStartLine = {
  type: "run_start"; at: string; run_id: string; anchor: string | null; messages: Message[];
  ignored: Ignored[]; request: RequestFields; source: "chat";
};
export type EventLine = { type: "event"; at: string; run_id: string; event: BaseEvent };
export type RunEndLine = { type: "run_end"; at: string; run_id: string; status: RunStatus; error: string | null };
export type MetaLine = { type: "meta"; at: string } & MetaFields;
export type Line = CreatedLine | RunStartLine | EventLine | RunEndLine | MetaLine;
export type NewLine = Line extends infer L ? (L extends Line ? Omit<L, "at"> : never) : never;

export const JOURNAL_SUFFIX = ".jsonl";
export const FSYNC_INTERVAL_MS = 1000;
export function journalPath(dir: string, id: string): string;     // throws ValidationError unless isSessionId(id)
export function idOfJournal(name: string): string | null;          // "<uuid>.jsonl" → uuid, anything else → null
export function parseJournal(text: string): { lines: Line[]; skipped: number };   // logs each skipped line's number only

export type Durability = "now" | "soon";                          // "now": fsync before resolving; "soon": within FSYNC_INTERVAL_MS
export type Clock = { now: () => number; setTimeout: (fn: () => void, ms: number) => unknown; clearTimeout: (h: unknown) => void };
export type JournalFs = {                                          // node:fs/promises by default; a test counts sync()
  open: (path: string, flags: "a" | "r") => Promise<{ appendFile(data: string): Promise<void>; sync(): Promise<void>; close(): Promise<void>; stat(): Promise<{ size: number }>; read(buf: Buffer, off: number, len: number, pos: number): Promise<{ bytesRead: number }> }>;
};
export class JournalWriter {
  constructor(path: string, opts?: { clock?: Clock; fs?: JournalFs; now?: () => Date });
  append(line: NewLine, durability: Durability): Promise<Line>;  // stamps `at`, appends one line, repairs a torn end before the first append
  close(): Promise<void>;                                          // flushes a pending "soon" fsync
}
```

**`lib/rebuild.ts`** (slice 1, task 3)

```ts
import type { Message } from "@ag-ui/client";
import type { Ignored, Line, MetaFields, RequestFields, RunStatus } from "./journal.ts";

export type Node = { message: Message; parentId: string | null; runId: string };
export type RunView = {
  run_id: string; anchor: string | null; new_messages: Message[]; ignored: Ignored[]; request: RequestFields;
  status: RunStatus | "incomplete"; error: string | null;
  started_at: string; ended_at: string | null; last_at: string;   // last_at: run_end's, else its last event's
  added: string[];                                                  // ids this run added, in order of first appearance (new messages first)
  events: number;
};
export type Conversation = {
  id: string; created_at: string | null;
  meta: Required<Pick<MetaFields, "tags" | "pinned" | "hidden">> & { title: string | null; deleted_at: string | null };
  first_user_text: string | null;
  nodes: Map<string, Node>;
  children: Map<string | null, string[]>;                           // null: the root's children
  runs: RunView[];                                                  // journal order of run_start
  tip: string | null;                                               // decision 9
  tip_run: string | null;
  last_line_at: string | null;
  skipped: number;                                                  // torn or unparsable lines
};
export function rebuild(id: string, lines: Line[]): Promise<Conversation>;
export function pathTo(conv: Conversation, id: string | null): Message[];   // root → id, inclusive; [] for null
export function isBoundary(conv: Conversation, id: string): boolean;        // a user message or a run's last added message
export function branchOfTip(conv: Conversation): Message[];                 // pathTo(conv, conv.tip)
```

**`lib/anchor.ts`** (slice 1, task 4)

```ts
import type { Message } from "@ag-ui/client";
import type { Ignored } from "./journal.ts";
import type { Conversation } from "./rebuild.ts";

export type Classification = { anchor: string | null; path: Message[]; newMessages: Message[]; ignored: Ignored[] };
export function canonical(message: Message): string;    // canonical JSON of role, content, toolCalls, toolCallId
export function classify(conv: Conversation | null, client: Message[]): Classification;
```

**`lib/export.ts`** (slice 2, task 1) and **`scripts/export-journals.ts`** (slice 2, task 2)

```ts
import type { Conversation } from "./rebuild.ts";
export type ArchiveMode = "live" | "final";
export type OpenWebUIChat = {
  id: string; title: string; created_at: number; updated_at: number; archived: boolean;
  meta: { tags: string[]; spe_deleted_at?: string };
  chat: { title: string; history: { messages: Record<string, unknown>; currentId: string | null }; messages: unknown[] };
};
export type Bundle = { exported_at: number; spe_archive_mode: ArchiveMode; chats: OpenWebUIChat[]; tags: { id: string; name: string }[]; notes: [] };
export function toOpenWebUIChat(conv: Conversation): OpenWebUIChat;
export function exportJournals(dir: string, mode: ArchiveMode): Promise<Bundle>;   // every <uuid>.jsonl, hidden and deleted included
```

`node scripts/export-journals.ts <journals dir> <bundle.json> <live|final>` (run in the image as
`docker run --rm --entrypoint node -v <dir>:/in:ro -v <out>:/out <chat-ui image> scripts/export-journals.ts /in /out/bundle.json <mode>`).

**`lib/sessions.ts`** (slice 3, task 1)

```ts
export type SessionMeta = { id: string; title: string; tags: string[]; pinned: boolean; hidden: boolean;
  created_at: string; updated_at: string; last_run_at: string | null };          // the browser's shape, unchanged
export type SessionView = Omit<SessionMeta, "last_run_at"> & { messages: Message[] };   // GET one: the tip's branch
export type MetaPatch = Partial<Pick<SessionMeta, "title" | "tags" | "pinned" | "hidden">>;
export type RunHandle = { cancel: () => void };
export type Shared = { queue: Map<string, Promise<unknown>>; running: Map<string, RunHandle>; closing: boolean };  // running keyed by runKey(threadId, runId)
export function shared(): Shared;                                  // Symbol.for("spe.sessions.queue")
export function withSession<T>(id: string, fn: () => Promise<T>): Promise<T>;
export class Journals {
  constructor(dir: string, opts?: { clock?: Clock; fs?: JournalFs; now?: () => Date });
  load(id: string): Promise<Conversation | null>;                  // null: no journal
  append(id: string, line: NewLine, durability: Durability): Promise<void>;   // under withSession by the caller; updates the index
  list(): Promise<SessionMeta[]>;                                  // from the index (Symbol.for("spe.sessions.index")), built on first use
  get(id: string): Promise<SessionView | null>;                    // null: missing, deleted, or no run added a message
  patch(id: string, patch: MetaPatch): Promise<SessionMeta | null>;
  softDelete(id: string): Promise<boolean>;
  isDeleted(id: string): Promise<boolean>;
}
export function defaultJournals(): Journals;
```

`normaliseTags`, `parsePatch`, `autoTitle`, `ValidationError` and `isSessionId` keep their names and behaviour.

**`lib/recorder.ts`** (slice 3, task 2): `export class SessionRecorder extends Middleware { constructor(journals: () => Journals, now?: () => Date); readonly fetch; run(input, next) }`;
`REFUSAL_MESSAGES` lists the four messages above; `SAVE_FAILED` and the "already running" refusal are gone.

**`lib/test-agent.ts`** (slice 1, task 1): a user message containing `echo-input` makes the reply's text the JSON
of `[{role, id}]` for every message the agent received. **`platform/dev/fake_agent.py`** (slice 3, task 5): the
same keyword, through `FunctionModel`, answers with the roles and ids pydantic-ai received.

**`write_run.py`** (slice 2, task 3): `is_compaction(item_or_message: dict) -> bool` (id starts with
`spe-compaction-`), `render_ignored(entries: list[dict]) -> str`, `render_status(run: dict) -> str`; `index.md` for
a bundle with `spe_archive_mode` gets `| # | Session | Tags | Created | Runs | Compactions | State |` (the as-built
AG-UI columns, inputs-for-plan, bullet 8) and the live/final line; an Open WebUI bundle (no `spe_archive_mode`)
renders byte-identically to before.

## File structure

| Path | Slice | What |
|---|---|---|
| `CHAT/lib/test-agent.ts`, `CHAT/lib/feasibility.test.ts` | 1 | `echo-input`; the runtime replaces `messages` |
| `CHAT/lib/journal.ts`, `lib/journal.test.ts` | 1 | format, parse, writer |
| `CHAT/lib/rebuild.ts`, `lib/rebuild.test.ts` | 1 | the rebuild |
| `CHAT/lib/anchor.ts`, `lib/anchor.test.ts` | 1 | classification |
| `CHAT/lib/export.ts`, `lib/export.test.ts`, `CHAT/scripts/export-journals.ts`, `CHAT/Dockerfile` | 2 | exporter in the image |
| `platform/dev/tests/fixtures/agui-record/*.jsonl`, `*.bundle.json` | 2 | fixture journals and the bundles exported from them (committed) |
| `ARCHIVE/write_run.py`, `platform/dev/tests/test_write_run_agui.py` | 2 | status, ignored, compaction, AG-UI index |
| `CHAT/lib/sessions.ts`, `lib/sessions.test.ts`, `lib/api.ts`, `lib/api.test.ts`, `app/api/sessions/**` | 3 | the store on journals |
| `CHAT/lib/recorder.ts`, `lib/recorder.test.ts`, `lib/clone.test.ts`, `lib/shutdown.ts`, `lib/reconcile.ts`, `app/api/copilotkit/[[...slug]]/route.ts` | 3 | the route on journals |
| `platform/ansible/roles/run_archive/tasks/export.yml`, `tasks/write.yml`; `ARCHIVE/write_agui_run.py` (deleted), `platform/dev/tests/test_write_agui_run.py` (deleted or reduced to `write_run.py` cases) | 3 | archive switch (barrier kept) |
| `platform/dev/fake_agent.py`, `CHAT/scripts/check-built-server.mjs`, `scripts/check-shutdown.mjs`, `platform/dev/e2e/sessions.py` | 3 | `echo-input`, checks read journals |
| `CHAT/README.md`, `docs/getting-started.md`, `platform/ansible/README.md`, `platform/coder/README.md`, `docs/knowledge/agui-chat-sessions.md` | 3 | storage described |
| `docs/superpowers/plans/2026-11-03-agui-conversation-record/evidence/slice-3/` | 3 | early output samples 1 and 2 |
| `platform/ansible/roles/run_archive/tasks/export.yml`, `playbooks/destroy.yml`, `playbooks/archive.yml` | 4 | live copy, final barrier (`spe_archive_final`) |
| `platform/dev/e2e/sessions.py` | 4 | devtools edit, close tab, restore on tip |
| `platform/ansible/roles/agui/tasks/checks.yml` | 4 | agent key not in the sandbox (17) |
| `threats/TM-007-*.md` | 4 | decision 18 |
| spec `README.md` status, `06-chat-ui.md`, `14-archive.md` (as-built paragraph), `clarifications.md` | 3, 4 | built |

`CHAT` is `platform/agui/copilotkit-chat`, `ARCHIVE` `platform/ansible/roles/run_archive/files`.

## PR slices

N = 4. Sequential: slice n+1 starts from `main` after slice n merged; slices 2–4 also wait for #18 (above). The
session merges each PR itself once the checks in `AGENTS.md`, *Overrides*, pass.

| n/N | Branch | Tasks | Delivers | Est. LOC | Reviewer checks | File | Status |
|---|---|---|---|---|---|---|---|
| 1/4 | `impl/agui-conversation-record-1-history` | 4 | **feasibility check** (decision 5) first; journal format and writer, rebuild, anchor, all unwired | ~1,100 | `npm test`; `npm run build` | [slice-1-history.md](slice-1-history.md) | planned |
| 2/4 | `impl/agui-conversation-record-2-export` | 3 | exporter in the image; `write_run.py` renders AG-UI chats (status, ignored, compaction, columns) | ~800 | `npm test`; `docker build` + exporter run in the image; `pytest platform/dev/tests` | [slice-2-export.md](slice-2-export.md) | planned |
| 3/4 | `impl/agui-conversation-record-3-route` | 5 | the store, the run route and the API on journals; archive exports journals (barrier kept); built-server check; **early output** samples 1 and 2 | ~1,500 | `npm test`; `npm run build`; `check-built-server.mjs`; `check-shutdown.mjs`; pytest; `--syntax-check`; e2e `sessions.py` | [slice-3-route.md](slice-3-route.md) | planned |
| 4/4 | `impl/agui-conversation-record-4-live-archive` | 5 | live archive and final barrier (decision 30); Playwright for decisions 6, 13, 24–26; key check (17); TM-007 (18); dev VM acceptance; spec marked built | ~700 | e2e `sessions.py`; `verify.yml` and `archive.yml` on the dev VM; `validate.py` | [slice-4-live-archive.md](slice-4-live-archive.md) | planned |

Slice 3 is past the guide's ~5 tasks by size, not count, and stays one unit (ruling 2): split, `main` would hold
journals the archive does not export, or a route that writes what the session API cannot read. It names two
mid-slice handoff points, each after a commit with `npm test` green: **after task 2** (store and route on
journals; API and archive next) and **after task 4** (archive switched; the checks, docs and samples next). A
reviewer looks first at `SessionRecorder.run` and `classify`.

**What the user sees, and when.** Slice 1's PR body carries the feasibility verdict (task 1's test output, and
what the test agent received). Slice 3's PR body carries the spec's two early-output samples, from the built
server with `fake_agent.py`: the `curl` with a fabricated assistant turn and a forged `spe-compaction-` marker,
the agent's echo, the journal lines; and the rendered `chats/01-*.md` of that session and of a normal session with
tool calls. It asks the user whether the ignored content and run statuses are clear to someone analysing a run,
and whether the browser should also show the ignored content. Slice 4 does not wait for the answer, but a change
it asks for (decisions 2, 6, 16) is rewritten into slice 4's task text by a commit on `main` before slice 4
starts, never left in a handoff.

## Review Focus

Inputs the spec implies that no acceptance check exercises; each line's test is in the named task.

1. **A client history whose messages arrive out of journal order** (the browser reorders, or devtools moves a
   reply above its question): the anchor is still the latest client message the journal holds, and every
   reordered message is `edited` only if its compared fields differ, never `fabricated`. Slice 1, task 4
   (`reordered history keeps the anchor and flags nothing`).
2. **A new user message reusing an id the journal holds in another branch** (a tab that resends an old message
   after the other tab ran): it is not a new message; the run has none and is refused, with the id recorded as
   `edited` only if its content differs. Slice 1, task 4 (`a known id after the anchor is not new`).
3. **A journal whose `created` line is torn or missing** (a crash during the first `run_start`): the rebuild
   still yields the runs it can parse, `created_at` falls back to the first parsed line's `at`, and the session
   lists. Slice 1, task 3 (`journal without a created line`).
4. **An event for a run whose `run_start` was never written or was skipped as torn**: the rebuild skips the
   event (logged by run id), never attaches it to another run. Slice 1, task 3 (`orphan event is skipped`).
5. **A title, tag or message with Markdown or HTML in the archive** (`# x`, `<script>`, a pipe in a title): the
   `index.md` table cell escapes `|` and newlines, and chat text renders inside fences or as escaped text, so the
   run directory's structure cannot be forged from a session. Slice 2, task 3 (`title with a pipe and a heading`).

## Proposed spec clarifications

Each is added by the slice that verifies it, with the next free number and status `folded`, and the spec text
updated in the same commit.

- **Slice 3: the as-built archive paragraph goes.** §14's "Until the record is built…" paragraph and the
  README's status line are rewritten as built (the barrier still runs in every archive until slice 4).
- **Slice 4: the record is built.** The README status, §6's "wait for the record" sentence and §14's barrier
  sentence for the as-built sessions are rewritten.

## Handoffs

[`handoffs/`](handoffs/): read only the newest (`ls handoffs | tail -1`).
