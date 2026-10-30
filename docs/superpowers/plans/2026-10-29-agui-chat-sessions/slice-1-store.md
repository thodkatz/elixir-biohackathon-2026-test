# Slice 1/3: the store — sessions on disk, the recorder, the session API, the volume

Delivers the server half of chat sessions, with no visible change in the page: `lib/sessions.ts` (one JSON file
per session, validated ids, atomic writes, one process-wide per-session queue), `lib/recorder.ts` (AG-UI
`Middleware` on the `spe` agent that records each run's conversation and outcome), `lib/api.ts` with the
`/api/sessions` routes, the `chat-sessions` volume at `/data` in `chat-ui`, `/data/sessions` in the image, the
slow scripted run in `platform/dev/fake_agent.py`, and `scripts/check-built-server.mjs` for the two properties a
unit test cannot show. The page (`app/page.tsx`) is untouched: a reload still starts a new conversation, and that
text stays until slice 2 changes the behaviour (spec §3, last paragraph).

**Implements:** spec [`2026-10-29-agui-chat-sessions-design.md`](../../specs/2026-10-29-agui-chat-sessions-design.md)
§1 *Storage and the session record*, §2 *Recording and the session API*, §5 *Security and limits* (input limits,
no keys, size and failures), §6 *Testing* (chat UI unit tests, the built-server checks, the image build, the fake
agent) and *Inputs for the plan* (the first task of slice 1, the canary ladder's isolation). Decisions **1**
(task 2 `recordRun creates a version-1 file…`, task 3 `RUN_FINISHED: … schema-valid version-1 file`, task 5 the
image build and hardened run), **2** (task 2 `isSessionId…`, `the store refuses an invalid id…`; task 3 `refused
runs…`; task 4 `ids that are not canonical UUID v4…`), **3** (task 2 `a write interrupted…`, `20 concurrent
metadata updates…`; task 5 `check-built-server.mjs` check 2), **4** (task 3: the seven termination tests, `a
second run on a running session…`, `PATCH and DELETE during a run…`; task 5 check 1), **5** (task 4 `PATCH with
messages, runs, id…`, `a new session is absent from the list…`), **6** (task 2 `softDelete…`, task 3 `refused
runs…`, task 4 `DELETE: 204…`), **7** (task 2 `autoTitle…`, `recordRun… merges`; task 3 `PATCH and DELETE during
a run…`), **8** (task 2 `tags are normalised or refused`), **13** (task 3 `neither the request's nor the agent's
bearer key…`). Not here: decision 1's `docker inspect` on an instance and decision 13's key scan (slice 3,
`checks.yml`); decision 4's closing-the-tab check end to end (slice 2's Playwright run).

**Branch:** `impl/agui-chat-sessions-1-store`, from `main` after the plan merged. Global constraints, shared
interfaces and Review Focus: [plan README](README.md). Paths below are relative to the repository root unless a
step `cd`s; `CHAT` means `platform/agui/copilotkit-chat`.

**Verified facts this slice builds on** (read in the installed packages, `node_modules` of the main checkout,
2026-10-30):

- `@ag-ui/client` 1.0.2 exports `Middleware` (`run(input, next)`; protected `runNextWithState(input, next)`,
  which yields `{event, messages, state}` after each event is applied) and re-exports `@ag-ui/core`
  (`EventType`, `Message`, `RunAgentInput`, `BaseEvent`). `AbstractAgent.use()` adds middlewares;
  `AbstractAgent.clone()` copies them (`e.middlewares=[...this.middlewares]`), so one middleware object serves
  every clone. Its Observable is rxjs 7.8.1.
- `@copilotkit/runtime` 1.79, `handle-run.mjs`: `cloneAgentForRequest` is `agents[id].clone()` per request,
  then `setMessages(input.messages)` and `threadId = input.threadId`. The in-memory runner runs `runAgent()`
  detached from the client, throws "Thread already running" for a second concurrent run of a thread, and its
  `stop()` calls `agent.abortRun()`.
- `HttpAgent.abortRun()` is `this.abortController.abort()`; the HTTP transform turns the `AbortError` into
  `{type: RUN_ERROR, message, code: "abort"}` and completes the stream instead of erroring it. So the stop button
  reaches the recorder as `RUN_ERROR` `code: "abort"` (plan README, *Proposed spec clarifications*, 1).
- `node --test lib/` does **not** work on Node 24.21 (`Cannot find module '…/lib'`): the test script passes the
  glob `'lib/*.test.ts'`, which `node --test` expands itself.

**Tried in scratch before writing this file** (2026-10-30, Node 24.21.0, a copy of `CHAT` with the main
checkout's `node_modules`): every file below, as written here, gave `npm test` **42 pass, 0 fail** (2 s);
`npm run build` passed (routes `/api/sessions` and `/api/sessions/[id]` listed, the `.ts` imports resolved by
Turbopack); `node scripts/check-built-server.mjs` printed `check-built-server: all checks passed` (4 PATCHes
during the run, one waited for the delayed save); `docker build` succeeded and a run with the compose hardening
(`--read-only`, the two tmpfs, `--cap-drop ALL`, `no-new-privileges`) on a fresh volume saved
`/data/sessions/<id>.json` owned by uid 1000, mode 0600, and `GET /api/sessions` listed it; the fake agent's
"slow" run took 10 s and ended `RUN_FINISHED`. Two mutation checks: with `withSession` calling `fn()` directly,
`20 concurrent metadata updates…` fails; with the recorder leaving the running set only after its write,
`a run started right after a stopped one…` fails (refused as "already running").

**Additions to the README's shared interfaces** (no listed signature changes): `lib/test-agent.ts` exports
`startTestAgent(delayMs?: number): Promise<TestAgent>` and `type TestAgent = { url: string; requests: {
headers: IncomingMessage["headers"]; body: any }[]; close: () => Promise<void> }` (test helper, kept out of the
image). The recorder refuses with these `RUN_ERROR` messages: `"invalid session"`, `"this session was
deleted"`, `"this session is already running"`, `"the chat UI is shutting down"` (when `shared().closing`),
`"this session could not be read"` (the file does not parse). `RunHandle.cancel()` ends the run with
`RUN_ERROR` `{code: "cancelled", message: "the run was stopped"}` after the save. A run leaves
`shared().running` at the moment its write joins the queue, so slice 2's drain is "until `running` is empty,
then until `queue` is empty". The save-failed event is `{type: CUSTOM, name: SAVE_FAILED, value: {session:
<id>}}`. Test-only env `SPE_SESSIONS_TEST_SAVE_DELAY_MS`: `recordRun` waits that long under the session's queue,
between its read and its write. Error bodies of the session API: `"invalid session id"` (400), `"invalid session
metadata"` (400), `"the request body is too large"` (413), `"no such session"` (404), `"the session store failed;
see the chat-ui logs"` (500).

**One process.** `chat-ui` is one Node process (`node server.js`), so the per-session queue on `globalThis` is
enough; a second process would need a file lock (spec §1). The comment above `shared()` says so.

### Task 1: the clone gate — `npm test`, the test agent, `lib/clone.test.ts`, spec clarification 1

**Files:** Modify: `CHAT/package.json`, `CHAT/package-lock.json`, `CHAT/tsconfig.json`, `docs/superpowers/specs/2026-10-29-agui-chat-sessions-design.md`,
`docs/superpowers/plans/2026-10-29-agui-chat-sessions/README.md` (header line, clarification 1). Create: `CHAT/lib/test-agent.ts`.
Test: `CHAT/lib/clone.test.ts`.

**Interfaces:** Consumes: `@ag-ui/client` 1.0.2 (`HttpAgent`, `Middleware`, `EventType`), rxjs 7.8.1. Produces:
`npm test`; `startTestAgent(delayMs?)` and `TestAgent` (scripted by the last user message: `hang`, `boom`,
`error`, `eof`, `crash`, anything else echoes and finishes after `delayMs`), used by tasks 3 and 4.

**Decisions:** none directly; this is the spec's feasibility gate (*Inputs for the plan*, first task of slice 1)
and it pins plan README clarification 1 (`abortRun() mid-stream reaches the middleware as RUN_ERROR with code
abort`).

**If the gate fails** (either clone test, after checking the test itself against the facts above): stop the
slice. Try once an `HttpAgent` subclass overriding `run()` and `clone()` (the spec's named alternative) in the
same test file; if that passes, record it as a ruling in the handoff (*decision, why, cost if wrong*) and
continue with the recorder as that subclass. If it fails too, the plan stops (spec, *Inputs for the
plan*): do not fall back to a browser-side save, which would break decisions 4 and 5. Commit the failing test on
the branch, write a handoff saying what failed and what was read in the packages, say in the draft PR's body that
the spec needs a clarification with a revised design before any further task, and end the session.

- [ ] **Step 1: Write the test agent** `CHAT/lib/test-agent.ts`

```ts
// Test helper: a tiny AG-UI agent over SSE (node:http), scripted by the last user message.
//   contains "hang": RUN_STARTED and one text chunk, then nothing until the client goes away
//   contains "boom": HTTP 500 before any event
//   contains "error": RUN_STARTED then RUN_ERROR
//   contains "eof": RUN_STARTED and a text message, then the stream ends without a terminal event
//   contains "crash": RUN_STARTED and one text chunk, then the connection is destroyed
//   anything else: a text message echoing it, then RUN_FINISHED (after `delayMs`, default 0)
import { createServer } from "node:http";
import type { IncomingMessage, Server } from "node:http";
import type { AddressInfo } from "node:net";

export type TestAgent = {
  url: string;
  requests: { headers: IncomingMessage["headers"]; body: any }[];
  close: () => Promise<void>;
};

export async function startTestAgent(delayMs = 0): Promise<TestAgent> {
  const requests: TestAgent["requests"] = [];
  const server: Server = createServer((req, res) => {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", async () => {
      const body = JSON.parse(raw);
      requests.push({ headers: req.headers, body });
      const users = (body.messages ?? []).filter((m: any) => m.role === "user");
      const text = String(users.at(-1)?.content ?? "");
      if (text.includes("boom")) {
        res.writeHead(500, { "content-type": "application/json" }).end('{"detail":"agent down"}');
        return;
      }
      res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
      const send = (event: object) => res.write(`data: ${JSON.stringify(event)}\n\n`);
      const ids = { threadId: body.threadId, runId: body.runId };
      const messageId = `reply-${body.runId}`;
      send({ type: "RUN_STARTED", ...ids });
      if (text.includes("error")) {
        send({ type: "RUN_ERROR", message: "scripted failure" });
        res.end();
        return;
      }
      send({ type: "TEXT_MESSAGE_START", messageId, role: "assistant" });
      send({ type: "TEXT_MESSAGE_CONTENT", messageId, delta: `echo: ${text}` });
      if (text.includes("hang")) return; // the client's abort or close ends it
      if (text.includes("crash")) {
        setTimeout(() => res.socket?.destroy(), 20);
        return;
      }
      send({ type: "TEXT_MESSAGE_END", messageId });
      if (text.includes("eof")) {
        res.end();
        return;
      }
      if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
      send({ type: "RUN_FINISHED", ...ids });
      res.end();
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}/agent`,
    requests,
    close: () =>
      new Promise<void>((resolve) => {
        server.closeAllConnections();
        server.close(() => resolve());
      }),
  };
}
```

- [ ] **Step 2: Write the gate test** `CHAT/lib/clone.test.ts`

```ts
// The feasibility gate (spec, "Inputs for the plan", first task of slice 1): AG-UI middleware
// attached with agent.use() survives the runtime's per-request clone(), keeps per-run state
// per clone, and sees the stop button (abortRun) as RUN_ERROR with code "abort".
import { test } from "node:test";
import assert from "node:assert/strict";
import { EventType, HttpAgent, Middleware } from "@ag-ui/client";
import type { AbstractAgent, BaseEvent, Message, RunAgentInput } from "@ag-ui/client";
import { finalize, map, tap } from "rxjs";
import type { Observable } from "rxjs";
import { startTestAgent } from "./test-agent.ts";

type Seen = { threadId: string; types: string[]; messages: Message[]; errorCode?: string };

class Probe extends Middleware {
  seen: Seen[] = [];
  onEvent: (event: BaseEvent) => void = () => {};
  run(input: RunAgentInput, next: AbstractAgent): Observable<BaseEvent> {
    const state: Seen = { threadId: input.threadId, types: [], messages: [] }; // per run, in this closure
    return this.runNextWithState(input, next).pipe(
      tap(({ event, messages }) => {
        state.types.push(event.type);
        state.messages = messages;
        if (event.type === EventType.RUN_ERROR) state.errorCode = (event as any).code;
        this.onEvent(event);
      }),
      map(({ event }) => event),
      finalize(() => this.seen.push(state)),
    );
  }
}

function user(id: string, content: string): Message {
  return { id, role: "user", content } as Message;
}

test("middleware survives clone() and keeps per-run state per clone", async () => {
  const server = await startTestAgent(50);
  try {
    const probe = new Probe();
    const agent = new HttpAgent({ url: server.url });
    agent.use(probe);
    const a = agent.clone();
    const b = agent.clone();
    a.threadId = "thread-a";
    a.setMessages([user("u-a", "first question")]);
    b.threadId = "thread-b";
    b.setMessages([user("u-b", "second question")]);
    await Promise.all([a.runAgent({ runId: "run-a" }), b.runAgent({ runId: "run-b" })]);

    assert.equal(probe.seen.length, 2);
    const byThread = Object.fromEntries(probe.seen.map((s) => [s.threadId, s]));
    for (const [thread, question] of [["thread-a", "first question"], ["thread-b", "second question"]]) {
      const s = byThread[thread];
      assert.equal(s.types[0], EventType.RUN_STARTED);
      assert.equal(s.types.at(-1), EventType.RUN_FINISHED);
      assert.deepEqual(
        s.messages.map((m) => [m.role, m.content]),
        [["user", question], ["assistant", `echo: ${question}`]],
      );
    }
  } finally {
    await server.close();
  }
});

test("abortRun() mid-stream reaches the middleware as RUN_ERROR with code abort", async () => {
  const server = await startTestAgent();
  try {
    const probe = new Probe();
    const agent = new HttpAgent({ url: server.url });
    agent.use(probe);
    const c = agent.clone();
    c.threadId = "thread-c";
    c.setMessages([user("u-c", "please hang")]);
    probe.onEvent = (event) => {
      if (event.type === EventType.TEXT_MESSAGE_CONTENT) c.abortRun();
    };
    await c.runAgent({ runId: "run-c" }).catch(() => {});
    assert.equal(probe.seen.length, 1);
    const s = probe.seen[0];
    assert.equal(s.types.at(-1), EventType.RUN_ERROR);
    assert.equal(s.errorCode, "abort");
  } finally {
    await server.close();
  }
});
```

- [ ] **Step 3: Run it to see it fail**

Run: `(cd platform/agui/copilotkit-chat && npm ci && npm test)`
Expected: FAIL: `npm error Missing script: "test"`. (The gate test itself is meant to pass once it can run: it
pins library behaviour the design depends on. Note that `node --test` given a glob that matches nothing exits 0
with `tests 0`, so always check the count.)

- [ ] **Step 4: Add the test script, list `rxjs`, allow `.ts` imports**

`CHAT/package.json` becomes (only `scripts.test` and `dependencies.rxjs` are new; `rxjs` 7.8.1 is already in
`package-lock.json` as a dependency of `@ag-ui/client`, so `npm ci` installs nothing new):

```json
{
  "name": "spe-chat-ui",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "test": "COPILOTKIT_TELEMETRY_DISABLED=true DO_NOT_TRACK=1 node --test --disable-warning=MODULE_TYPELESS_PACKAGE_JSON 'lib/*.test.ts'"
  },
  "dependencies": {
    "@ag-ui/client": "1.0.2",
    "@copilotkit/react-core": "1.79.0",
    "@copilotkit/runtime": "1.79.0",
    "next": "16.4.1",
    "react": "19.3.1",
    "react-dom": "19.3.1",
    "rxjs": "7.8.1"
  },
  "devDependencies": {
    "@types/node": "26.6.5",
    "@types/react": "19.3.0",
    "typescript": "6.0.3"
  }
}
```

`COPILOTKIT_TELEMETRY_DISABLED` and `DO_NOT_TRACK` keep task 3's in-process CopilotKit runtime from calling out;
`--disable-warning=MODULE_TYPELESS_PACKAGE_JSON` silences Node's notice that `.ts` files with `import` are read
as ESM (adding `"type": "module"` would change how Next.js loads the project, so it is not done).

In `CHAT/tsconfig.json`, add after `"incremental": false,`:

```json
    "allowImportingTsExtensions": true,
```

Then refresh the lock's root entry: `(cd platform/agui/copilotkit-chat && npm install --package-lock-only
--no-audit --no-fund)`. Expect `git diff --stat` to show `package-lock.json` with 1–2 changed lines (the `rxjs`
line in the root package's `dependencies`) and no new package.

- [ ] **Step 5: Run it**

Run: `(cd platform/agui/copilotkit-chat && npm ci && npm test)`
Expected: PASS, `tests 2`: `middleware survives clone() and keeps per-run state per clone`, `abortRun()
mid-stream reaches the middleware as RUN_ERROR with code abort`. If either fails, follow *If the gate fails*
above.

- [ ] **Step 6: Fold clarification 1 into the spec**

In `docs/superpowers/specs/2026-10-29-agui-chat-sessions-design.md`:

1. Header: `**Latest clarification:** none.` → `**Latest clarification:** 1.`
2. Decision 4's acceptance check: `stop (unsubscribed), and terminal event followed by unsubscription` →
   `the stop button (\`RUN_ERROR\` with \`code: "abort"\`), unsubscription before a terminal event, and terminal
   event followed by unsubscription`.
3. §2's termination table becomes:

```markdown
   | Termination | `status` |
   |---|---|
   | `RUN_FINISHED` | `completed` |
   | `RUN_ERROR` with `code: "abort"` (the stop button: the runner's `stop` aborts the agent's request) | `cancelled` |
   | any other `RUN_ERROR`, or the stream errors (including an HTTP error from the agent before any event) | `failed` |
   | the stream completes without a terminal event | `failed` |
   | unsubscribed before a terminal event | `cancelled` |
```

4. A new section after *Inputs for the plan* (the spec then passes 400 lines by a few; it stays one file, as the
   guide's limit is approximate and the new section is history, not design):

```markdown
## Clarifications

1. **The stop button arrives as `RUN_ERROR` with `code: "abort"` and is recorded `cancelled`** (2026-10-30;
   slice 1/3). The runner's `stop` calls `HttpAgent.abortRun()`, which aborts the agent's request; the HTTP
   transform of `@ag-ui/client` 1.0.2 turns the `AbortError` into a `RUN_ERROR` event with `code: "abort"` and
   ends the stream, rather than the client unsubscribing. Unsubscription before a terminal event stays
   `cancelled`. *Reason:* read in `@ag-ui/client` 1.0.2 and pinned by `lib/clone.test.ts`. *Amends:* §2
   (termination table), decision 4. *Status:* folded.
```

In the plan's `README.md`, the header line `(decisions 1–15; latest clarification: none)` → `(decisions 1–15;
latest clarification: 1)`, and *Proposed spec clarifications*, item 1 gains `Added by slice 1 (folded).` at
its end.

- [ ] **Step 7: Run the suites and commit**

Run: `(cd platform/agui/copilotkit-chat && npm test && npm run build)`
Expected: 2 pass; `next build` ends with the route table and no type error.

```bash
git add platform/agui/copilotkit-chat/package.json platform/agui/copilotkit-chat/package-lock.json \
  platform/agui/copilotkit-chat/tsconfig.json platform/agui/copilotkit-chat/lib/test-agent.ts \
  platform/agui/copilotkit-chat/lib/clone.test.ts \
  docs/superpowers/specs/2026-10-29-agui-chat-sessions-design.md \
  docs/superpowers/plans/2026-10-29-agui-chat-sessions/README.md
git commit -s -m "Chat UI: npm test and the clone gate for the session recorder

AG-UI middleware attached with use() survives the runtime's per-request
clone(), keeps per-run state per clone, and sees the stop button as
RUN_ERROR code abort. Spec clarification 1 folds the last into §2."
```

### Task 2: the store — `lib/sessions.ts`

**Files:** Create: `CHAT/lib/sessions.ts`. Test: `CHAT/lib/sessions.test.ts`.

**Interfaces:** Consumes: `import type { Message } from "@ag-ui/client"`. Produces: everything the README lists
under `lib/sessions.ts`, with exactly those signatures. `SessionStore.dir` is a public readonly field (tests and
the recorder test read it). `read` throws on a file that does not parse or is not a `version: 1` record for
that id (`"session file <id>.json is not a version-1 session"`); `list` skips such files and logs each with
`console.error` (name and parser message only). New files are created with mode `0600`.

**Decisions:** 1 (the record's shape, `recordRun creates a version-1 file…`), 2 (`isSessionId…`, `the store
refuses an invalid id before building a path`), 3 (`a write interrupted before the rename…`, `20 concurrent
metadata updates…`), 6 (`softDelete keeps the file…`), 7 (`autoTitle…`, `recordRun… merges into the latest
record`), 8 (`tags are normalised or refused`). Review Focus 1 (`an unparsable session file is skipped and
logged; read throws`), 2 (`leftover .tmp- files are never listed…`), 3 (`autoTitle keeps an astral character…`).

Choices the spec leaves open, made here: a `PATCH` title has its whitespace collapsed and trimmed and must be
1–200 code points; an empty `PATCH` body (`{}`) is a 400 ("nothing to change"); tags over 20 *after*
de-duplication are refused; `softDelete` also sets `updated_at`.

- [ ] **Step 1: Write the failing tests** `CHAT/lib/sessions.test.ts`

```ts
// The store (spec §1): decisions 1, 2, 3, 7, 8 and Review Focus 1-3.
import { test, mock } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { Message } from "@ag-ui/client";
import {
  SessionStore, ValidationError, autoTitle, isSessionId, normaliseTags, parsePatch, shared,
} from "./sessions.ts";
import type { RunEntry, SessionRecord } from "./sessions.ts";

const T0 = new Date("2026-10-29T10:00:00.000Z");
const at = (seconds: number) => new Date(T0.getTime() + seconds * 1000);

async function tmpStore(): Promise<SessionStore> {
  return new SessionStore(await fs.mkdtemp(path.join(os.tmpdir(), "sessions-")));
}

function user(content: unknown): Message {
  return { id: randomUUID(), role: "user", content } as Message;
}

function run(status: RunEntry["status"] = "completed"): RunEntry {
  return { run_id: randomUUID(), started_at: T0.toISOString(), ended_at: at(1).toISOString(), status };
}

async function seeded(store: SessionStore, text = "hello"): Promise<string> {
  const id = randomUUID();
  await store.recordRun(id, [user(text)], run(), at(1));
  return id;
}

test("isSessionId accepts only canonical lower-case UUID v4 (decision 2)", () => {
  assert.equal(isSessionId(randomUUID()), true);
  for (const bad of [
    "../x", "a/b", "", "6F1C0D2E-1234-4ABC-8DEF-0123456789AB", "6f1c0d2e-1234-1abc-8def-0123456789ab",
    "6f1c0d2e-1234-4abc-cdef-0123456789ab", "6f1c0d2e12344abc8def0123456789ab",
    `${randomUUID()}\n`, `${randomUUID()}.json`, 42, null, undefined,
  ]) {
    assert.equal(isSessionId(bad), false, String(bad));
  }
});

test("the store refuses an invalid id before building a path (decision 2)", async () => {
  const store = await tmpStore();
  await assert.rejects(store.read("../x"), ValidationError);
  await assert.rejects(store.patch("a/b", { pinned: true }, T0), ValidationError);
  await assert.rejects(store.recordRun("../../etc/x", [], run(), T0), ValidationError);
  assert.deepEqual(await fs.readdir(store.dir), []);
});

test("tags are normalised or refused (decision 8)", () => {
  const cases: [unknown, string[]][] = [
    [[" Exfil ", "DNS", "exfil"], ["exfil", "dns"]],
    [["a.b_c-1"], ["a.b_c-1"]],
    [["x".repeat(32)], ["x".repeat(32)]],
    [Array.from({ length: 20 }, (_, i) => `t${i}`), Array.from({ length: 20 }, (_, i) => `t${i}`)],
    [[...Array.from({ length: 20 }, (_, i) => `t${i}`), "T0"], Array.from({ length: 20 }, (_, i) => `t${i}`)],
    [[], []],
  ];
  for (const [input, expected] of cases) assert.deepEqual(normaliseTags(input), expected);
  for (const bad of [
    "exfil", [""], ["   "], ["x".repeat(33)], ["has space"], ["ümlaut"], ["a/b"], [1], [null],
    Array.from({ length: 21 }, (_, i) => `t${i}`),
  ]) {
    assert.throws(() => normaliseTags(bad), ValidationError, JSON.stringify(bad));
  }
});

test("parsePatch takes title, tags, pinned and hidden only", () => {
  assert.deepEqual(parsePatch({ title: "  New\n title ", tags: ["A"], pinned: true, hidden: false }), {
    title: "New title", tags: ["a"], pinned: true, hidden: false,
  });
  for (const bad of [
    {}, { messages: [] }, { runs: [] }, { id: randomUUID() }, { deleted_at: null }, { title: 5 },
    { title: "" }, { title: "x".repeat(201) }, { pinned: "yes" }, { hidden: 1 }, { tags: "a" },
    null, [], "title", 3,
  ]) {
    assert.throws(() => parsePatch(bad), ValidationError, JSON.stringify(bad));
  }
  assert.equal(parsePatch({ title: "😀".repeat(200) }).title, "😀".repeat(200)); // 200 code points
});

test("autoTitle: first user text, whitespace collapsed, 60 code points, Untitled (decision 7)", () => {
  assert.equal(autoTitle([user("  List\n\tthe   home directory ")]), "List the home directory");
  assert.equal(autoTitle([user("x".repeat(80))]), "x".repeat(60));
  assert.equal(autoTitle([user([{ type: "text", text: "from parts" }])]), "from parts");
  assert.equal(autoTitle([]), "Untitled");
  assert.equal(autoTitle([user("   ")]), "Untitled");
});

test("autoTitle keeps an astral character at the cut whole (Review Focus 3)", () => {
  const title = autoTitle([user("a".repeat(59) + "😀" + "tail")]);
  assert.equal(title, "a".repeat(59) + "😀");
  assert.equal(Array.from(title).length, 60);
  assert.equal(title.isWellFormed(), true);
});

test("recordRun creates a version-1 file, then merges into the latest record (decisions 1, 4, 7)", async () => {
  const store = await tmpStore();
  const id = randomUUID();
  const first = run();
  await store.recordRun(id, [user("first question")], first, at(1));
  let record = (await store.read(id)) as SessionRecord;
  assert.deepEqual(Object.keys(record).sort(), [
    "created_at", "deleted_at", "hidden", "id", "messages", "pinned", "runs", "tags", "title",
    "title_source", "updated_at", "version",
  ]);
  assert.equal(record.version, 1);
  assert.equal(record.title, "first question");
  assert.equal(record.title_source, "auto");
  assert.equal(record.created_at, first.started_at);
  assert.deepEqual(record.runs, [first]);
  assert.equal((await fs.stat(path.join(store.dir, `${id}.json`))).mode & 0o777, 0o600);

  await store.patch(id, { title: "Mine", tags: ["x"] }, at(2));
  await store.recordRun(id, [user("other text")], run("failed"), at(3));
  record = (await store.read(id)) as SessionRecord;
  assert.equal(record.title, "Mine");
  assert.equal(record.title_source, "user");
  assert.deepEqual(record.tags, ["x"]);
  assert.equal(record.runs.length, 2);
  assert.equal(record.updated_at, at(3).toISOString());
});

test("a write interrupted before the rename leaves the previous file intact (decision 3)", async () => {
  const store = await tmpStore();
  const id = await seeded(store, "kept");
  const before = await fs.readFile(path.join(store.dir, `${id}.json`), "utf8");
  const rename = mock.method(fs, "rename", async () => {
    throw new Error("crash before rename");
  });
  try {
    await assert.rejects(store.patch(id, { title: "lost" }, at(5)), /crash before rename/);
  } finally {
    rename.mock.restore();
  }
  assert.equal(await fs.readFile(path.join(store.dir, `${id}.json`), "utf8"), before);
  assert.deepEqual(await fs.readdir(store.dir), [`${id}.json`]); // the temp file is removed
});

test("20 concurrent metadata updates to one session all land (decision 3)", async () => {
  const store = await tmpStore();
  const id = await seeded(store);
  // Each update reads the file, changes one field and writes it back. Unserialised, a writer
  // that read before another's write puts the other field back: one field's update is lost.
  const patches = Array.from({ length: 20 }, (_, i) =>
    [{ title: `t${i}` }, { tags: [`g${i}`] }, { pinned: i % 8 === 2 }, { hidden: i % 8 === 3 }][i % 4],
  );
  const results = await Promise.all(patches.map((p, i) => store.patch(id, p, at(10 + i))));
  assert.equal(results.every((m) => m !== null), true);
  const record = (await store.read(id)) as SessionRecord;
  assert.deepEqual(
    [record.title, record.tags, record.pinned, record.hidden, record.updated_at],
    ["t16", ["g17"], true, true, at(29).toISOString()],
  );
  assert.equal(record.messages.length, 1); // the run recorded before is still there
  assert.equal(shared().queue.has(id), false); // the chain is dropped once drained
});

test("list: newest updated_at first, deleted left out, hidden kept, capped at 1000", async () => {
  const store = await tmpStore();
  const a = await seeded(store, "a");
  const b = await seeded(store, "b");
  const c = await seeded(store, "c");
  await store.patch(a, { hidden: true }, at(30));
  await store.patch(c, { pinned: true }, at(20));
  await store.softDelete(b, at(40));
  const list = await store.list();
  assert.deepEqual(list.map((m) => m.id), [a, c]);
  assert.deepEqual(Object.keys(list[0]).sort(), ["created_at", "hidden", "id", "pinned", "tags", "title", "updated_at"]);
  assert.equal(list[0].hidden, true);

  const many = await tmpStore();
  for (let i = 0; i < 1005; i++) {
    const id = randomUUID();
    await fs.writeFile(path.join(many.dir, `${id}.json`), JSON.stringify({
      version: 1, id, title: `s${i}`, title_source: "auto", tags: [], pinned: false, hidden: false,
      created_at: T0.toISOString(), updated_at: at(i).toISOString(), deleted_at: null, messages: [], runs: [],
    }));
  }
  const capped = await many.list();
  assert.equal(capped.length, 1000);
  assert.equal(capped[0].title, "s1004");
});

test("an unparsable session file is skipped and logged; read throws (Review Focus 1)", async () => {
  const store = await tmpStore();
  const good = await seeded(store, "good");
  const broken = randomUUID();
  const future = randomUUID();
  await fs.writeFile(path.join(store.dir, `${broken}.json`), "{ not json");
  await fs.writeFile(path.join(store.dir, `${future}.json`), JSON.stringify({ version: 2, id: future }));
  const logged = mock.method(console, "error", () => {});
  try {
    assert.deepEqual((await store.list()).map((m) => m.id), [good]);
    assert.equal(logged.mock.callCount(), 2);
  } finally {
    logged.mock.restore();
  }
  await assert.rejects(store.read(broken));
  await assert.rejects(store.read(future), /not a version-1 session/);
});

test("leftover .tmp- files are never listed or read as sessions (Review Focus 2)", async () => {
  const store = await tmpStore();
  const id = await seeded(store, "real");
  const record = await fs.readFile(path.join(store.dir, `${id}.json`), "utf8");
  await fs.writeFile(path.join(store.dir, `${id}.json.tmp-${randomUUID()}`), record.replace("real", "stale"));
  await fs.writeFile(path.join(store.dir, `${randomUUID()}.json.tmp-x`), record);
  await fs.writeFile(path.join(store.dir, "notes.txt"), "x");
  const list = await store.list();
  assert.deepEqual(list.map((m) => [m.id, m.title]), [[id, "real"]]);
});

test("softDelete keeps the file with deleted_at; patch and delete then find nothing (decision 6)", async () => {
  const store = await tmpStore();
  const id = await seeded(store);
  assert.equal(await store.softDelete(id, at(5)), true);
  assert.equal(await store.softDelete(id, at(6)), false);
  assert.equal(await store.patch(id, { pinned: true }, at(7)), null);
  const record = (await store.read(id)) as SessionRecord;
  assert.equal(record.deleted_at, at(5).toISOString());
  assert.equal(record.pinned, false);
  assert.equal(await store.softDelete(randomUUID(), at(8)), false);
  assert.equal(await store.patch(randomUUID(), { pinned: true }, at(8)), null);
});

test("a missing sessions directory lists as empty", async () => {
  const store = new SessionStore(path.join(os.tmpdir(), `absent-${randomUUID()}`));
  assert.deepEqual(await store.list(), []);
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `(cd platform/agui/copilotkit-chat && node --test --disable-warning=MODULE_TYPELESS_PACKAGE_JSON lib/sessions.test.ts)`
Expected: FAIL: `Cannot find module '…/lib/sessions.ts'`.

- [ ] **Step 3: Write the store** `CHAT/lib/sessions.ts`

```ts
// Chat sessions on disk: one JSON file per session, /data/sessions/<uuid>.json (spec §1).
// The only module that touches the filesystem. Every id is checked by isSessionId() before a
// path is built from it.
import fs from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { Message } from "@ag-ui/client";

export type RunStatus = "completed" | "failed" | "cancelled";
export type RunEntry = { run_id: string; started_at: string; ended_at: string; status: RunStatus };
export type SessionRecord = {
  version: 1;
  id: string;
  title: string;
  title_source: "auto" | "user";
  tags: string[];
  pinned: boolean;
  hidden: boolean;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  messages: Message[];
  runs: RunEntry[];
};
export type SessionMeta = Pick<SessionRecord, "id" | "title" | "tags" | "pinned" | "hidden" | "created_at" | "updated_at">;
export type SessionView = Omit<SessionRecord, "deleted_at" | "runs">;
export type MetaPatch = Partial<Pick<SessionRecord, "title" | "tags" | "pinned" | "hidden">>;

export class ValidationError extends Error {}

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const TAG = /^[a-z0-9._-]{1,32}$/;
const MAX_TAGS = 20;
const MAX_TITLE = 200;
const AUTO_TITLE = 60;
const MAX_LIST = 1000;

export function isSessionId(value: unknown): value is string {
  return typeof value === "string" && UUID_V4.test(value);
}

export function normaliseTags(value: unknown): string[] {
  if (!Array.isArray(value)) throw new ValidationError("tags must be a list");
  const tags: string[] = [];
  for (const raw of value) {
    if (typeof raw !== "string") throw new ValidationError("a tag must be a string");
    const tag = raw.trim().toLowerCase();
    if (!TAG.test(tag)) throw new ValidationError("a tag is 1-32 characters of a-z 0-9 . _ -");
    if (!tags.includes(tag)) tags.push(tag);
  }
  if (tags.length > MAX_TAGS) throw new ValidationError("at most 20 tags");
  return tags;
}

export function parsePatch(body: unknown): MetaPatch {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    throw new ValidationError("the body must be a JSON object");
  }
  const input = body as Record<string, unknown>;
  const keys = Object.keys(input);
  if (keys.length === 0) throw new ValidationError("nothing to change");
  const patch: MetaPatch = {};
  for (const key of keys) {
    const value = input[key];
    if (key === "title") {
      if (typeof value !== "string") throw new ValidationError("title must be a string");
      const title = value.replace(/\s+/g, " ").trim();
      if (title.length === 0 || Array.from(title).length > MAX_TITLE) {
        throw new ValidationError("title must be 1-200 characters");
      }
      patch.title = title;
    } else if (key === "tags") {
      patch.tags = normaliseTags(value);
    } else if (key === "pinned" || key === "hidden") {
      if (typeof value !== "boolean") throw new ValidationError(`${key} must be true or false`);
      patch[key] = value;
    } else {
      throw new ValidationError("unknown key");
    }
  }
  return patch;
}

function messageText(message: Message): string {
  const content = (message as { content?: unknown }).content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((part) => (part && typeof part === "object" && part.type === "text" ? String(part.text ?? "") : ""))
      .join(" ");
  }
  return "";
}

export function autoTitle(messages: Message[]): string {
  const first = messages.find((m) => m.role === "user");
  const text = first ? messageText(first).replace(/\s+/g, " ").trim() : "";
  // Cut by code point (Array.from), never inside a surrogate pair.
  const title = Array.from(text).slice(0, AUTO_TITLE).join("").trim();
  return title || "Untitled";
}

// One queue and one running set per process, shared by every route bundle: Next.js bundles each
// route separately, so module state would be per bundle, but globalThis is per process. chat-ui
// is one Node process (`node server.js`); a second process would need a file lock instead.
export type RunHandle = { cancel: () => void };
export type Shared = { queue: Map<string, Promise<unknown>>; running: Map<string, RunHandle>; closing: boolean };
const KEY = Symbol.for("spe.sessions.queue");

export function shared(): Shared {
  const g = globalThis as typeof globalThis & { [KEY]?: Shared };
  g[KEY] ??= { queue: new Map(), running: new Map(), closing: false };
  return g[KEY];
}

// Runs fn after every earlier fn for the same id has settled. The map holds only the tail of
// each chain, which never rejects, and drops it once nothing is queued behind it.
export function withSession<T>(id: string, fn: () => Promise<T>): Promise<T> {
  const { queue } = shared();
  const previous = queue.get(id) ?? Promise.resolve();
  const result = previous.then(fn);
  const tail = result.then(
    () => undefined,
    () => undefined,
  );
  queue.set(id, tail);
  void tail.then(() => {
    if (queue.get(id) === tail) queue.delete(id);
  });
  return result;
}

function toMeta(r: SessionRecord): SessionMeta {
  return { id: r.id, title: r.title, tags: r.tags, pinned: r.pinned, hidden: r.hidden, created_at: r.created_at, updated_at: r.updated_at };
}

function checkRecord(value: unknown, id: string): SessionRecord {
  const r = value as SessionRecord;
  const ok =
    typeof r === "object" && r !== null && r.version === 1 && r.id === id &&
    typeof r.title === "string" && Array.isArray(r.tags) && Array.isArray(r.messages) &&
    Array.isArray(r.runs) && typeof r.updated_at === "string";
  if (!ok) throw new Error(`session file ${id}.json is not a version-1 session`);
  return r;
}

export class SessionStore {
  readonly dir: string;

  constructor(dir: string) {
    this.dir = dir;
  }

  private file(id: string): string {
    if (!isSessionId(id)) throw new ValidationError("invalid session id");
    return path.join(this.dir, `${id}.json`);
  }

  async read(id: string): Promise<SessionRecord | null> {
    let text: string;
    try {
      text = await fs.readFile(this.file(id), "utf8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
      throw error;
    }
    return checkRecord(JSON.parse(text), id);
  }

  async write(record: SessionRecord): Promise<void> {
    const target = this.file(record.id);
    const tmp = `${target}.tmp-${randomUUID()}`;
    try {
      const handle = await fs.open(tmp, "wx", 0o600);
      try {
        await handle.writeFile(JSON.stringify(record, null, 2) + "\n");
        await handle.sync();
      } finally {
        await handle.close();
      }
      await fs.rename(tmp, target);
    } catch (error) {
      await fs.rm(tmp, { force: true }).catch(() => {});
      throw error;
    }
  }

  async list(): Promise<SessionMeta[]> {
    let names: string[];
    try {
      names = await fs.readdir(this.dir);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
      throw error;
    }
    const metas: SessionMeta[] = [];
    for (const name of names) {
      const id = name.endsWith(".json") ? name.slice(0, -".json".length) : "";
      if (!isSessionId(id)) continue; // also skips <id>.json.tmp-* leftovers
      try {
        const record = await this.read(id);
        if (record && record.deleted_at === null) metas.push(toMeta(record));
      } catch (error) {
        console.error(`sessions: skipping ${name}:`, error instanceof Error ? error.message : error);
      }
    }
    metas.sort((a, b) => (a.updated_at < b.updated_at ? 1 : a.updated_at > b.updated_at ? -1 : 0));
    return metas.slice(0, MAX_LIST);
  }

  async patch(id: string, patch: MetaPatch, now: Date): Promise<SessionMeta | null> {
    this.file(id); // throws ValidationError before anything is queued
    return withSession(id, async () => {
      const record = await this.read(id);
      if (!record || record.deleted_at !== null) return null;
      if (patch.title !== undefined) {
        record.title = patch.title;
        record.title_source = "user";
      }
      if (patch.tags !== undefined) record.tags = patch.tags;
      if (patch.pinned !== undefined) record.pinned = patch.pinned;
      if (patch.hidden !== undefined) record.hidden = patch.hidden;
      record.updated_at = now.toISOString();
      await this.write(record);
      return toMeta(record);
    });
  }

  async softDelete(id: string, now: Date): Promise<boolean> {
    this.file(id);
    return withSession(id, async () => {
      const record = await this.read(id);
      if (!record || record.deleted_at !== null) return false;
      record.deleted_at = now.toISOString();
      record.updated_at = record.deleted_at;
      await this.write(record);
      return true;
    });
  }

  // §2 Finalise: re-read under the queue, so metadata changed during the run survives.
  // Queued synchronously when called (an async function runs up to its first await), so a
  // drain of shared().queue started right after sees it.
  async recordRun(id: string, messages: Message[], run: RunEntry, now: Date): Promise<void> {
    this.file(id);
    return withSession(id, async () => {
      const stamp = now.toISOString();
      const record: SessionRecord = (await this.read(id)) ?? {
        version: 1, id, title: autoTitle(messages), title_source: "auto", tags: [], pinned: false,
        hidden: false, created_at: run.started_at, updated_at: stamp, deleted_at: null, messages: [], runs: [],
      };
      record.messages = messages;
      record.runs.push(run);
      record.updated_at = stamp;
      await this.write(record);
    });
  }
}

export function defaultStore(): SessionStore {
  return new SessionStore(process.env.SPE_SESSIONS_DIR || "/data/sessions");
}
```

- [ ] **Step 4: Run them to see them pass**

Run: `(cd platform/agui/copilotkit-chat && npm test)`
Expected: PASS, `tests 16` (14 here, 2 from task 1).

- [ ] **Step 5: Type check and commit**

Run: `(cd platform/agui/copilotkit-chat && npm run build)`; expected: no type error.

```bash
git add platform/agui/copilotkit-chat/lib/sessions.ts platform/agui/copilotkit-chat/lib/sessions.test.ts
git commit -s -m "Chat UI: session store with validated ids, atomic writes and a per-session queue"
```

### Task 3: the recorder — `lib/recorder.ts`

**Files:** Create: `CHAT/lib/recorder.ts`. Modify: `CHAT/lib/sessions.ts` (the test-only save delay). Test:
`CHAT/lib/recorder.test.ts`.

**Interfaces:** Consumes: task 2's `SessionStore`, `shared()`, `withSession`, `isSessionId`, `RunHandle`,
`RunStatus`; task 1's `startTestAgent`; `@copilotkit/runtime/v2` `CopilotRuntime`, `createCopilotRuntimeHandler`
(the decision-13 test drives the real runtime). Produces: `SessionRecorder` (`constructor(store: () =>
SessionStore, now?: () => Date)`, `run(input, next): Observable<BaseEvent>`), `SAVE_FAILED`, the refusal
messages and `RunHandle.cancel()` behaviour listed at the top of this file, and `SPE_SESSIONS_TEST_SAVE_DELAY_MS`
(slice 3's reconciliation test sets it on the built server).

**Decisions:** 1 (`RUN_FINISHED: completed, messages, auto title, a schema-valid version-1 file`), 2 and 6
(`refused runs: RUN_STARTED then RUN_ERROR, the agent never called, nothing written`), 4 (one test per row of
§2's table as amended in task 1: `RUN_FINISHED…`, `RUN_ERROR…`, `an HTTP error from the agent before any
event…`, `a stream error…`, `EOF without a terminal event…`, `unsubscribed before a terminal event…`, `the stop
button (abortRun, RUN_ERROR code abort)…`, `a terminal event followed by unsubscription…`; plus `a second run on
a running session is refused…` and `PATCH and DELETE during a run survive its finalisation`), 7 (the same
test: a user title survives a run), 13 (`neither the request's nor the agent's bearer key reaches the session
file`: `Authorization: Bearer <k1>` on the request into the runtime, agent key `<k2>` in the `HttpAgent`'s
headers). Also: `a failed save: spe.session_save_failed before the terminal event, logged without content`,
`RunHandle.cancel() ends a running session's run as cancelled`, `closing: new runs are refused…`,
`SPE_SESSIONS_TEST_SAVE_DELAY_MS holds a stopped run's save…`, `a run started right after a stopped one is
admitted and recorded after it`.

How it works (spec §2): every call of `run()` builds its state in its own closure (the middleware object is
shared by every clone). **Admit** under the session's queue (`withSession`): refuse an invalid id, a closing
process, a running session, a deleted or unreadable file, by emitting `RUN_STARTED` then `RUN_ERROR` without
calling `next`; otherwise put a `RunHandle` in `shared().running`. **During**: keep the latest `messages` from
`runNextWithState`, synchronously on each event. **Finalise** once: the first terminal event, stream error,
stream end, unsubscription or `cancel()` wins. Event-driven terminations are chained (`chain`) so the write
completes before the terminal event is passed on; unsubscription writes after. `recordRun` joins the queue
synchronously, so the run leaves `running` as soon as its write is queued (and only if its own handle is still
there): a run started right after a stopped one is queued behind the write instead of being refused.

- [ ] **Step 1: Write the failing tests** `CHAT/lib/recorder.test.ts`

```ts
// The recorder (spec §2): decisions 1, 2, 4, 6, 7, 13 and the §2 termination table.
import { test, mock } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { EventType, HttpAgent } from "@ag-ui/client";
import type { BaseEvent, Message, RunAgentInput } from "@ag-ui/client";
import { CopilotRuntime, createCopilotRuntimeHandler } from "@copilotkit/runtime/v2";
import { SAVE_FAILED, SessionRecorder } from "./recorder.ts";
import { SessionStore, shared } from "./sessions.ts";
import type { RunEntry, SessionRecord } from "./sessions.ts";
import { startTestAgent } from "./test-agent.ts";
import type { TestAgent } from "./test-agent.ts";

async function setup(delayMs = 0) {
  const store = new SessionStore(await fs.mkdtemp(path.join(os.tmpdir(), "recorder-")));
  const server = await startTestAgent(delayMs);
  const recorder = new SessionRecorder(() => store);
  return { store, server, recorder, agent: () => new HttpAgent({ url: server.url }) };
}

function input(threadId: string, text: string, history: Message[] = []): RunAgentInput {
  return {
    threadId, runId: randomUUID(), state: {}, tools: [], context: [], forwardedProps: {},
    messages: [...history, { id: randomUUID(), role: "user", content: text } as Message],
  };
}

type Outcome = { events: BaseEvent[]; error?: unknown };

// Calls the recorder as AbstractAgent.runAgent does, on an agent prepared as the runtime prepares
// its per-request clone (runNextWithState applies events to the agent's own messages).
// `stopWhen` unsubscribes right after the matching event.
function drive(
  recorder: SessionRecorder, runInput: RunAgentInput, agent: HttpAgent,
  stopWhen?: (event: BaseEvent) => boolean,
): Promise<Outcome> {
  agent.threadId = runInput.threadId;
  agent.setMessages(runInput.messages);
  return new Promise((resolve) => {
    const events: BaseEvent[] = [];
    const sub = recorder.run(runInput, agent).subscribe({
      next: (event) => {
        events.push(event);
        if (stopWhen?.(event)) {
          queueMicrotask(() => {
            sub.unsubscribe();
            resolve({ events });
          });
        }
      },
      error: (error) => resolve({ events, error }),
      complete: () => resolve({ events }),
    });
  });
}

// A save after unsubscription lands after drive() returns: wait for the session's queue.
async function settled(id: string): Promise<void> {
  for (let i = 0; i < 100 && (shared().running.has(id) || shared().queue.has(id)); i++) {
    await new Promise((r) => setTimeout(r, 10));
  }
}

async function onlyRun(store: SessionStore, id: string): Promise<[SessionRecord, RunEntry]> {
  const record = (await store.read(id)) as SessionRecord;
  assert.equal(record.runs.length, 1, "exactly one runs[] entry");
  return [record, record.runs[0]];
}

const types = (o: Outcome) => o.events.map((e) => e.type);

test("RUN_FINISHED: completed, messages, auto title, a schema-valid version-1 file (decisions 1, 4, 7)", async () => {
  const { store, server, recorder, agent } = await setup();
  try {
    const id = randomUUID();
    const runInput = input(id, "list the home directory");
    const out = await drive(recorder, runInput, agent());
    assert.equal(types(out).at(-1), EventType.RUN_FINISHED);
    const [record, run] = await onlyRun(store, id);
    assert.deepEqual(Object.keys(record).sort(), [
      "created_at", "deleted_at", "hidden", "id", "messages", "pinned", "runs", "tags", "title",
      "title_source", "updated_at", "version",
    ]);
    assert.equal(record.version, 1);
    assert.equal(record.id, id);
    assert.deepEqual([record.title, record.title_source, record.tags, record.pinned, record.hidden, record.deleted_at],
      ["list the home directory", "auto", [], false, false, null]);
    for (const stamp of [record.created_at, record.updated_at, run.started_at, run.ended_at]) {
      assert.match(stamp, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/);
    }
    assert.deepEqual(Object.keys(run).sort(), ["ended_at", "run_id", "started_at", "status"]);
    assert.deepEqual([run.run_id, run.status], [runInput.runId, "completed"]);
    assert.deepEqual(record.messages.map((m) => [m.role, m.content]),
      [["user", "list the home directory"], ["assistant", "echo: list the home directory"]]);
    assert.equal(shared().running.has(id), false);
  } finally {
    await server.close();
  }
});

for (const [name, text, expected] of [
  ["RUN_ERROR", "error please", "failed"],
  ["an HTTP error from the agent before any event", "boom", "failed"],
  ["a stream error (connection lost)", "crash now", "failed"],
  ["EOF without a terminal event", "eof now", "failed"],
] as const) {
  test(`${name}: ${expected}, recorded once`, async () => {
    const { store, server, recorder, agent } = await setup();
    try {
      const id = randomUUID();
      await drive(recorder, input(id, text), agent());
      await settled(id);
      const [record, run] = await onlyRun(store, id);
      assert.equal(run.status, expected);
      assert.equal(record.messages[0].content, text);
    } finally {
      await server.close();
    }
  });
}

test("unsubscribed before a terminal event: cancelled, partial answer kept", async () => {
  const { store, server, recorder, agent } = await setup();
  try {
    const id = randomUUID();
    await drive(recorder, input(id, "hang on"), agent(), (e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
    await settled(id);
    const [record, run] = await onlyRun(store, id);
    assert.equal(run.status, "cancelled");
    assert.deepEqual(record.messages.map((m) => m.role), ["user", "assistant"]);
  } finally {
    await server.close();
  }
});

test("the stop button (abortRun, RUN_ERROR code abort): cancelled", async () => {
  const { store, server, recorder } = await setup();
  try {
    const id = randomUUID();
    const base = new HttpAgent({ url: server.url });
    base.use(recorder);
    const clone = base.clone(); // as the runtime does per request
    clone.threadId = id;
    clone.setMessages(input(id, "hang until stopped").messages);
    await clone.runAgent({ runId: randomUUID() }, {
      onEvent: ({ event }) => {
        if (event.type === EventType.TEXT_MESSAGE_CONTENT) clone.abortRun();
      },
    }).catch(() => {});
    await settled(id);
    const [, run] = await onlyRun(store, id);
    assert.equal(run.status, "cancelled");
  } finally {
    await server.close();
  }
});

test("a terminal event followed by unsubscription: completed, exactly one entry", async () => {
  const { store, server, recorder, agent } = await setup();
  try {
    const id = randomUUID();
    await drive(recorder, input(id, "quick"), agent(), (e) => e.type === EventType.RUN_FINISHED);
    await settled(id);
    const [, run] = await onlyRun(store, id);
    assert.equal(run.status, "completed");
  } finally {
    await server.close();
  }
});

test("refused runs: RUN_STARTED then RUN_ERROR, the agent never called, nothing written (decisions 2, 6)", async () => {
  const { store, server, recorder, agent } = await setup();
  try {
    const deleted = randomUUID();
    await drive(recorder, input(deleted, "first"), agent());
    await store.softDelete(deleted, new Date());
    const before = await fs.readFile(path.join(store.dir, `${deleted}.json`), "utf8");
    const calls = server.requests.length;
    for (const [id, message] of [
      ["../x", "invalid session"],
      ["6F1C0D2E-1234-4ABC-8DEF-0123456789AB", "invalid session"],
      [deleted, "this session was deleted"],
    ]) {
      const out = await drive(recorder, input(id, "again"), agent());
      assert.deepEqual(types(out), [EventType.RUN_STARTED, EventType.RUN_ERROR]);
      assert.equal((out.events[1] as { message?: string }).message, message);
    }
    assert.equal(server.requests.length, calls);
    assert.deepEqual(await fs.readdir(store.dir), [`${deleted}.json`]);
    assert.equal(await fs.readFile(path.join(store.dir, `${deleted}.json`), "utf8"), before);
  } finally {
    await server.close();
  }
});

test("a second run on a running session is refused and never reaches the agent (decision 4)", async () => {
  const { store, server, recorder, agent } = await setup(200);
  try {
    const id = randomUUID();
    const first = drive(recorder, input(id, "slow first"), agent());
    while (server.requests.length === 0) await new Promise((r) => setTimeout(r, 5));
    const second = await drive(recorder, input(id, "second"), agent());
    assert.deepEqual(types(second), [EventType.RUN_STARTED, EventType.RUN_ERROR]);
    assert.equal((second.events[1] as { message?: string }).message, "this session is already running");
    await first;
    assert.equal(server.requests.length, 1);
    const [record] = await onlyRun(store, id);
    assert.equal(record.messages[0].content, "slow first");
  } finally {
    await server.close();
  }
});

test("PATCH and DELETE during a run survive its finalisation (decisions 4, 6, 7)", async () => {
  const { store, server, recorder, agent } = await setup(200);
  try {
    const id = randomUUID();
    const first = input(id, "first question");
    await drive(recorder, first, agent());
    const history = ((await store.read(id)) as SessionRecord).messages;
    const running = drive(recorder, input(id, "second question", history), agent());
    while (server.requests.length < 2) await new Promise((r) => setTimeout(r, 5));
    await store.patch(id, { title: "Renamed", tags: ["dns"] }, new Date());
    await store.softDelete(id, new Date());
    await running;
    const record = (await store.read(id)) as SessionRecord;
    assert.deepEqual([record.title, record.title_source, record.tags], ["Renamed", "user", ["dns"]]);
    assert.notEqual(record.deleted_at, null);
    assert.equal(record.runs.length, 2);
    assert.equal(record.messages.at(-1)?.content, "echo: second question");
    // a later run would be refused: the session is deleted; the title stays the user's
    await drive(recorder, input(id, "third"), agent());
    assert.equal(((await store.read(id)) as SessionRecord).runs.length, 2);
  } finally {
    await server.close();
  }
});

test("a failed save: spe.session_save_failed before the terminal event, logged without content", async () => {
  const { server, store } = await setup();
  try {
    class Failing extends SessionStore {
      async recordRun(): Promise<void> {
        throw new Error("ENOSPC: no space left on device");
      }
    }
    const failing = new Failing(store.dir);
    const recorder = new SessionRecorder(() => failing);
    const logged = mock.method(console, "error", () => {});
    const id = randomUUID();
    let out: Outcome;
    try {
      out = await drive(recorder, input(id, "secret canary text"), new HttpAgent({ url: server.url }));
    } finally {
      logged.mock.restore();
    }
    const tail = out.events.slice(-2);
    assert.deepEqual(tail.map((e) => e.type), [EventType.CUSTOM, EventType.RUN_FINISHED]);
    assert.equal((tail[0] as { name?: string }).name, SAVE_FAILED);
    assert.equal(logged.mock.callCount(), 1);
    assert.doesNotMatch(JSON.stringify(logged.mock.calls[0].arguments), /secret canary text/);
    assert.equal(shared().running.has(id), false);
  } finally {
    await server.close();
  }
});

test("RunHandle.cancel() ends a running session's run as cancelled", async () => {
  const { store, server, recorder, agent } = await setup();
  try {
    const id = randomUUID();
    const outcome = drive(recorder, input(id, "hang for shutdown"), agent());
    while (server.requests.length === 0) await new Promise((r) => setTimeout(r, 5));
    shared().running.get(id)?.cancel();
    const out = await outcome;
    const last = out.events.at(-1) as { type: string; code?: string };
    assert.deepEqual([last.type, last.code], [EventType.RUN_ERROR, "cancelled"]);
    const [, run] = await onlyRun(store, id);
    assert.equal(run.status, "cancelled");
  } finally {
    await server.close();
  }
});

test("closing: new runs are refused once shutdown has begun", async () => {
  const { server, recorder, agent } = await setup();
  shared().closing = true;
  try {
    const out = await drive(recorder, input(randomUUID(), "late"), agent());
    assert.deepEqual(types(out), [EventType.RUN_STARTED, EventType.RUN_ERROR]);
    assert.equal(server.requests.length, 0);
  } finally {
    shared().closing = false;
    await server.close();
  }
});

test("neither the request's nor the agent's bearer key reaches the session file (decision 13)", async () => {
  const { store, server } = await setup();
  try {
    const k1 = `k1-${randomUUID()}`; // sent by the browser to the runtime
    const k2 = `k2-${randomUUID()}`; // the runtime's agent key, sent to the agent
    const spe = new HttpAgent({ url: server.url, headers: { Authorization: `Bearer ${k2}` } });
    spe.use(new SessionRecorder(() => store));
    const handler = createCopilotRuntimeHandler({
      runtime: new CopilotRuntime({ agents: { spe } }),
      basePath: "/api/copilotkit",
    });
    const id = randomUUID();
    const response = await handler(new Request("http://chat-ui/api/copilotkit/agent/spe/run", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${k1}` },
      body: JSON.stringify(input(id, "hello through the runtime")),
    }));
    assert.equal(response.status, 200);
    await response.text(); // the whole SSE stream
    await settled(id);
    assert.equal(server.requests[0].headers.authorization, `Bearer ${k2}`); // the key was in play
    const text = await fs.readFile(path.join(store.dir, `${id}.json`), "utf8");
    assert.doesNotMatch(text, new RegExp(k1));
    assert.doesNotMatch(text, new RegExp(k2));
    const [record, run] = await onlyRun(store, id);
    assert.equal(run.status, "completed");
    assert.equal(record.messages.at(-1)?.content, "echo: hello through the runtime");
  } finally {
    await server.close();
  }
});

test("SPE_SESSIONS_TEST_SAVE_DELAY_MS holds a stopped run's save after the client has gone", async () => {
  const { store, server, recorder, agent } = await setup();
  process.env.SPE_SESSIONS_TEST_SAVE_DELAY_MS = "300";
  try {
    const id = randomUUID();
    await drive(recorder, input(id, "hang then stop"), agent(), (e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
    const stopped = Date.now();
    assert.equal(await store.read(id), null); // not yet saved
    await settled(id);
    assert.ok(Date.now() - stopped >= 250, "the save waited for the delay");
    const [, run] = await onlyRun(store, id);
    assert.equal(run.status, "cancelled");
  } finally {
    delete process.env.SPE_SESSIONS_TEST_SAVE_DELAY_MS;
    await server.close();
  }
});

test("a run started right after a stopped one is admitted and recorded after it", async () => {
  const { store, server, recorder, agent } = await setup();
  try {
    const id = randomUUID();
    await drive(recorder, input(id, "hang then stop"), agent(), (e) => e.type === EventType.TEXT_MESSAGE_CONTENT);
    const next = await drive(recorder, input(id, "right after"), agent());
    assert.equal(types(next).at(-1), EventType.RUN_FINISHED);
    const record = (await store.read(id)) as SessionRecord;
    assert.deepEqual(record.runs.map((r) => r.status), ["cancelled", "completed"]);
    assert.equal(shared().running.has(id), false);
  } finally {
    await server.close();
  }
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `(cd platform/agui/copilotkit-chat && node --test --disable-warning=MODULE_TYPELESS_PACKAGE_JSON lib/recorder.test.ts)`
Expected: FAIL: `Cannot find module '…/lib/recorder.ts'`.

- [ ] **Step 3: Write the recorder** `CHAT/lib/recorder.ts`

```ts
// The session recorder (spec §2): AG-UI middleware on the `spe` agent that records each run's
// conversation into its session file. One instance serves every clone of the agent, so all
// per-run state lives in the closure of run().
import { EventType, Middleware } from "@ag-ui/client";
import type { AbstractAgent, BaseEvent, Message, RunAgentInput } from "@ag-ui/client";
import { Observable } from "rxjs";
import type { Subscription } from "rxjs";
import { isSessionId, shared, withSession } from "./sessions.ts";
import type { RunHandle, RunStatus, SessionStore } from "./sessions.ts";

export const SAVE_FAILED = "spe.session_save_failed";

type Admission = { refused: string } | { refused: null };

// §2's table, for events: RUN_FINISHED completed; RUN_ERROR failed, or cancelled when it is the
// stop button (HttpAgent.abortRun() turns the aborted fetch into RUN_ERROR with code "abort").
function statusOf(event: BaseEvent): RunStatus | null {
  if (event.type === EventType.RUN_FINISHED) return "completed";
  if (event.type === EventType.RUN_ERROR) return (event as { code?: string }).code === "abort" ? "cancelled" : "failed";
  return null;
}

export class SessionRecorder extends Middleware {
  readonly store: () => SessionStore;
  readonly now: () => Date;

  constructor(store: () => SessionStore, now: () => Date = () => new Date()) {
    super();
    this.store = store;
    this.now = now;
  }

  run(input: RunAgentInput, next: AbstractAgent): Observable<BaseEvent> {
    return new Observable<BaseEvent>((out) => {
      const id = input.threadId;
      const { running } = shared();
      const startedAt = this.now().toISOString();
      let messages: Message[] = input.messages;
      let admitted = false;
      let finalised = false;
      let terminal: RunStatus | null = null; // status of the first terminal event seen
      let inner: Subscription | undefined;
      let chain: Promise<void> = Promise.resolve();

      const pass = (event: BaseEvent) => {
        if (!out.closed) out.next(event);
      };
      // Leaves the running set only if this run is still the one in it.
      const release = () => {
        if (running.get(id) === handle) running.delete(id);
      };
      // Exactly once per run: the first termination wins, every later one does nothing.
      // recordRun joins the session's queue synchronously, so the run leaves the running set as
      // soon as its write is queued: the next admission of this session queues behind the write
      // and is never refused by a run that has already ended.
      // Returns false when the write failed (logged here, without message content).
      const finalise = async (status: RunStatus): Promise<boolean> => {
        if (!admitted || finalised) return true;
        finalised = true;
        try {
          const run = { run_id: input.runId, started_at: startedAt, ended_at: this.now().toISOString(), status };
          const saving = this.store().recordRun(id, messages, run, this.now());
          release();
          await saving;
          return true;
        } catch (error) {
          console.error(`sessions: saving run ${input.runId} of ${id} failed:`, error instanceof Error ? error.message : error);
          return false;
        } finally {
          release();
        }
      };
      const saveFailed = (): BaseEvent =>
        ({ type: EventType.CUSTOM, name: SAVE_FAILED, value: { session: id } }) as BaseEvent;
      // A terminal event or stream end: write first, then pass the outcome on.
      const end = async (status: RunStatus, last: () => void) => {
        if (!(await finalise(status))) pass(saveFailed());
        last();
      };
      const handle: RunHandle = {
        cancel: () => {
          if (finalised) return;
          inner?.unsubscribe();
          chain = chain.then(() =>
            end("cancelled", () => {
              pass({ type: EventType.RUN_ERROR, message: "the run was stopped", code: "cancelled" } as BaseEvent);
              out.complete();
            }),
          );
        },
      };

      this.admit(id, handle).then((admission) => {
        if (admission.refused !== null) {
          pass({ type: EventType.RUN_STARTED, threadId: id, runId: input.runId } as BaseEvent);
          pass({ type: EventType.RUN_ERROR, message: admission.refused } as BaseEvent);
          out.complete();
          return;
        }
        admitted = true;
        if (out.closed) {
          // Unsubscribed while admission was pending: nothing reached the agent.
          finalised = true;
          release();
          return;
        }
        inner = this.runNextWithState(input, next).subscribe({
          next: ({ event, messages: latest }) => {
            // Synchronously, so a teardown right after a terminal event still records it.
            if (!finalised && terminal === null) messages = latest;
            terminal ??= statusOf(event);
            chain = chain.then(async () => {
              const status = statusOf(event);
              if (finalised || status === null) return pass(event);
              await end(status, () => pass(event));
            });
          },
          error: (error: unknown) => {
            chain = chain.then(() => end("failed", () => out.error(error)));
          },
          complete: () => {
            chain = chain.then(() => end("failed", () => out.complete()));
          },
        });
      });

      // Unsubscribed before a terminal event: cancelled, saved after the client has gone.
      return () => {
        inner?.unsubscribe();
        if (admitted && !finalised) void finalise(terminal ?? "cancelled");
      };
    });
  }

  // §2 Admit: under the session's queue, so it orders with every write to that session.
  private async admit(id: string, handle: RunHandle): Promise<Admission> {
    if (!isSessionId(id)) return { refused: "invalid session" };
    const { running } = shared();
    return withSession(id, async () => {
      if (shared().closing) return { refused: "the chat UI is shutting down" };
      if (running.has(id)) return { refused: "this session is already running" };
      let record;
      try {
        record = await this.store().read(id);
      } catch (error) {
        console.error(`sessions: reading ${id} failed:`, error instanceof Error ? error.message : error);
        return { refused: "this session could not be read" };
      }
      if (record?.deleted_at) return { refused: "this session was deleted" };
      running.set(id, handle);
      return { refused: null };
    });
  }
}
```

- [ ] **Step 4: Run them; only the save-delay test fails**

Run: `(cd platform/agui/copilotkit-chat && node --test --disable-warning=MODULE_TYPELESS_PACKAGE_JSON lib/recorder.test.ts)`
Expected: 16 pass, 1 fail: `SPE_SESSIONS_TEST_SAVE_DELAY_MS holds a stopped run's save…` (`the save waited for
the delay`).

- [ ] **Step 5: Add the test-only save delay to `recordRun`**

In `CHAT/lib/sessions.ts`, insert above `export class SessionStore {`:

```ts
// Test-only: SPE_SESSIONS_TEST_SAVE_DELAY_MS holds each recorded run's write that long, under the
// session's queue, so end-to-end checks can make a save land late. Unset in production.
function testSaveDelay(): Promise<void> {
  const ms = Number(process.env.SPE_SESSIONS_TEST_SAVE_DELAY_MS) || 0;
  return ms > 0 ? new Promise((resolve) => setTimeout(resolve, ms)) : Promise.resolve();
}

```

and in `recordRun`, between the `const record: SessionRecord = … ;` statement and `record.messages = messages;`:

```ts
      await testSaveDelay();
```

- [ ] **Step 6: Run everything**

Run: `(cd platform/agui/copilotkit-chat && npm test && npm run build)`
Expected: PASS, `tests 33` (2 + 14 + 17); no type error.

- [ ] **Step 7: Commit**

```bash
git add platform/agui/copilotkit-chat/lib/recorder.ts platform/agui/copilotkit-chat/lib/recorder.test.ts \
  platform/agui/copilotkit-chat/lib/sessions.ts
git commit -s -m "Chat UI: record each run into its session from the AG-UI stream

AG-UI middleware: admits one run per session under the session's queue,
keeps the latest messages and finalises once, with the status of spec
§2's table. Writes before passing a terminal event on, so a failed save
can be reported as spe.session_save_failed."
```

### Task 4: the session API — `lib/api.ts`, the routes, the recorder on `spe`

**Files:** Create: `CHAT/lib/api.ts`, `CHAT/app/api/sessions/route.ts`, `CHAT/app/api/sessions/[id]/route.ts`.
Modify: `CHAT/app/api/copilotkit/[[...slug]]/route.ts`. Test: `CHAT/lib/api.test.ts`.

**Interfaces:** Consumes: tasks 2 and 3. Produces: `listSessions(store)`, `getSession(store, id)`,
`patchSession(store, id, request)`, `deleteSession(store, id)`, each `Promise<Response>`; routes `GET
/api/sessions`, `GET`/`PATCH`/`DELETE /api/sessions/{id}` (slice 2's page calls them); the `spe` agent carries
`SessionRecorder(defaultStore)`.

**Decisions:** 2 (`ids that are not canonical UUID v4 get 400 from every route, no file created`), 5 (`PATCH with
messages, runs, id, deleted_at or an unknown key: 400, nothing changed`; `a new session is absent from the list
until a run on it ends`), 6 (`DELETE: 204, then gone from list, GET, PATCH and DELETE (404); the file kept`).
Spec §2's table: `GET one…`, `PATCH: 200 with the new metadata…`, `PATCH over 16 KB: 413…` (declared and
streamed bodies). Review Focus 1 (`store failures give the generic 500 and log no message content`), 4 (`PATCH
bodies that are not a JSON object: 400, nothing changed`).

- [ ] **Step 1: Write the failing tests** `CHAT/lib/api.test.ts`

```ts
// The session API (spec §2, Session API): decisions 2, 5, 6 and Review Focus 4.
import { test, mock } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { HttpAgent } from "@ag-ui/client";
import type { Message } from "@ag-ui/client";
import { deleteSession, getSession, listSessions, patchSession } from "./api.ts";
import { SessionRecorder } from "./recorder.ts";
import { SessionStore } from "./sessions.ts";
import type { SessionRecord } from "./sessions.ts";
import { startTestAgent } from "./test-agent.ts";

async function tmpStore(): Promise<SessionStore> {
  return new SessionStore(await fs.mkdtemp(path.join(os.tmpdir(), "api-")));
}

async function seeded(store: SessionStore, text = "hello"): Promise<string> {
  const id = randomUUID();
  const now = new Date();
  await store.recordRun(id, [{ id: randomUUID(), role: "user", content: text } as Message],
    { run_id: randomUUID(), started_at: now.toISOString(), ended_at: now.toISOString(), status: "completed" }, now);
  return id;
}

function patchRequest(body: string): Request {
  return new Request("http://chat-ui/api/sessions/x", {
    method: "PATCH", headers: { "content-type": "application/json" }, body,
  });
}

const BAD_IDS = ["../x", "a/b", "6F1C0D2E-1234-4ABC-8DEF-0123456789AB", "6f1c0d2e-1234-1abc-8def-0123456789ab", "x"];

test("ids that are not canonical UUID v4 get 400 from every route, no file created (decision 2)", async () => {
  const store = await tmpStore();
  for (const id of BAD_IDS) {
    for (const response of [
      await getSession(store, id),
      await patchSession(store, id, patchRequest('{"pinned":true}')),
      await deleteSession(store, id),
    ]) {
      assert.equal(response.status, 400, id);
      assert.deepEqual(await response.json(), { error: "invalid session id" });
    }
  }
  assert.deepEqual(await fs.readdir(store.dir), []);
});

test("GET one: the record without deleted_at and runs; 404 when missing", async () => {
  const store = await tmpStore();
  const id = await seeded(store);
  const response = await getSession(store, id);
  assert.equal(response.status, 200);
  const view = await response.json();
  assert.deepEqual(Object.keys(view).sort(), [
    "created_at", "hidden", "id", "messages", "pinned", "tags", "title", "title_source", "updated_at", "version",
  ]);
  assert.equal((await getSession(store, randomUUID())).status, 404);
});

test("PATCH with messages, runs, id, deleted_at or an unknown key: 400, nothing changed (decision 5)", async () => {
  const store = await tmpStore();
  const id = await seeded(store);
  const file = path.join(store.dir, `${id}.json`);
  const before = await fs.readFile(file, "utf8");
  for (const body of [
    { messages: [] }, { runs: [] }, { id: randomUUID() }, { deleted_at: null }, { colour: "red" },
    { title: "ok", messages: [] }, { tags: ["bad tag"] }, { pinned: "true" }, { title: "x".repeat(201) }, {},
  ]) {
    const response = await patchSession(store, id, patchRequest(JSON.stringify(body)));
    assert.equal(response.status, 400, JSON.stringify(body));
    assert.deepEqual(await response.json(), { error: "invalid session metadata" });
  }
  assert.equal(await fs.readFile(file, "utf8"), before);
});

test("PATCH bodies that are not a JSON object: 400, nothing changed (Review Focus 4)", async () => {
  const store = await tmpStore();
  const id = await seeded(store);
  const file = path.join(store.dir, `${id}.json`);
  const before = await fs.readFile(file, "utf8");
  for (const body of ["{not json", "", "[]", "null", '"title"', "42", "true", '[{"title":"x"}]']) {
    const response = await patchSession(store, id, patchRequest(body));
    assert.equal(response.status, 400, body);
    assert.deepEqual(await response.json(), { error: "invalid session metadata" });
  }
  assert.equal(await fs.readFile(file, "utf8"), before);
});

test("PATCH over 16 KB: 413, nothing changed", async () => {
  const store = await tmpStore();
  const id = await seeded(store);
  const file = path.join(store.dir, `${id}.json`);
  const before = await fs.readFile(file, "utf8");
  const big = JSON.stringify({ title: "x".repeat(16 * 1024) });
  const response = await patchSession(store, id, patchRequest(big));
  assert.equal(response.status, 413);
  assert.deepEqual(await response.json(), { error: "the request body is too large" });
  // the same body streamed without a content-length is cut off as it is read
  const streamed = new Request("http://chat-ui/api/sessions/x", {
    method: "PATCH", body: new Blob([big]).stream(), duplex: "half",
  } as RequestInit);
  assert.equal((await patchSession(store, id, streamed)).status, 413);
  assert.equal(await fs.readFile(file, "utf8"), before);
});

test("PATCH: 200 with the new metadata; title_source becomes user", async () => {
  const store = await tmpStore();
  const id = await seeded(store);
  const response = await patchSession(store, id, patchRequest('{"title":"Mine","tags":[" DNS "],"pinned":true}'));
  assert.equal(response.status, 200);
  const meta = await response.json();
  assert.deepEqual([meta.id, meta.title, meta.tags, meta.pinned, meta.hidden], [id, "Mine", ["dns"], true, false]);
  assert.deepEqual(Object.keys(meta).sort(), ["created_at", "hidden", "id", "pinned", "tags", "title", "updated_at"]);
  assert.equal(((await store.read(id)) as SessionRecord).title_source, "user");
  assert.equal((await patchSession(store, randomUUID(), patchRequest('{"pinned":true}'))).status, 404);
});

test("DELETE: 204, then gone from list, GET, PATCH and DELETE (404); the file kept (decision 6)", async () => {
  const store = await tmpStore();
  const id = await seeded(store);
  const other = await seeded(store, "other");
  assert.equal((await deleteSession(store, id)).status, 204);
  assert.deepEqual((await (await listSessions(store)).json()).map((m: { id: string }) => m.id), [other]);
  assert.equal((await getSession(store, id)).status, 404);
  assert.equal((await patchSession(store, id, patchRequest('{"pinned":true}'))).status, 404);
  assert.equal((await deleteSession(store, id)).status, 404);
  assert.notEqual(((await store.read(id)) as SessionRecord).deleted_at, null);
});

test("a new session is absent from the list until a run on it ends (decision 5)", async () => {
  const store = await tmpStore();
  const server = await startTestAgent(300);
  try {
    const id = randomUUID();
    const agent = new HttpAgent({ url: server.url });
    agent.use(new SessionRecorder(() => store));
    agent.threadId = id;
    agent.setMessages([{ id: randomUUID(), role: "user", content: "new chat" } as Message]);
    const run = agent.runAgent({ runId: randomUUID() });
    while (server.requests.length === 0) await new Promise((r) => setTimeout(r, 5));
    assert.deepEqual(await (await listSessions(store)).json(), []);
    assert.equal((await getSession(store, id)).status, 404);
    await run;
    assert.deepEqual((await (await listSessions(store)).json()).map((m: { id: string }) => m.id), [id]);
  } finally {
    await server.close();
  }
});

test("store failures give the generic 500 and log no message content (Review Focus 1)", async () => {
  const store = await tmpStore();
  const broken = randomUUID();
  await fs.writeFile(path.join(store.dir, `${broken}.json`), '{"version":1,"secret":"canary-123"');
  const logged = mock.method(console, "error", () => {});
  try {
    const response = await getSession(store, broken);
    assert.equal(response.status, 500);
    const text = await response.text();
    assert.deepEqual(JSON.parse(text), { error: "the session store failed; see the chat-ui logs" });
    assert.doesNotMatch(text, new RegExp(store.dir));
    assert.doesNotMatch(JSON.stringify(logged.mock.calls.map((c) => c.arguments)), /canary-123/);
    assert.equal((await listSessions(store)).status, 200); // the list skips it
  } finally {
    logged.mock.restore();
  }
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `(cd platform/agui/copilotkit-chat && node --test --disable-warning=MODULE_TYPELESS_PACKAGE_JSON lib/api.test.ts)`
Expected: FAIL: `Cannot find module '…/lib/api.ts'`.

- [ ] **Step 3: Write the handlers** `CHAT/lib/api.ts`

```ts
// The session API's handlers (spec §2, Session API), framework-free: the Next.js routes in
// app/api/sessions/ only call these. Error bodies are generic; details go to the server log.
import { ValidationError, isSessionId, parsePatch } from "./sessions.ts";
import type { SessionStore, SessionView } from "./sessions.ts";

const MAX_BODY = 16 * 1024;

function fail(status: number, error: string): Response {
  return Response.json({ error }, { status });
}

function serverError(what: string, error: unknown): Response {
  console.error(`sessions api: ${what}:`, error instanceof Error ? error.message : error);
  return fail(500, "the session store failed; see the chat-ui logs");
}

class TooLarge extends Error {}

// Reads at most MAX_BODY bytes; a larger body is refused without reading the rest.
async function readBody(request: Request): Promise<string> {
  const declared = Number(request.headers.get("content-length") ?? 0);
  if (declared > MAX_BODY) throw new TooLarge();
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BODY) {
      await reader.cancel();
      throw new TooLarge();
    }
    chunks.push(value);
  }
  return Buffer.concat(chunks).toString("utf8");
}

export async function listSessions(store: SessionStore): Promise<Response> {
  try {
    return Response.json(await store.list());
  } catch (error) {
    return serverError("list", error);
  }
}

export async function getSession(store: SessionStore, id: string): Promise<Response> {
  if (!isSessionId(id)) return fail(400, "invalid session id");
  try {
    const record = await store.read(id);
    if (!record || record.deleted_at !== null) return fail(404, "no such session");
    const { deleted_at: _deleted, runs: _runs, ...view } = record;
    return Response.json(view satisfies SessionView);
  } catch (error) {
    return serverError(`read ${id}`, error);
  }
}

export async function patchSession(store: SessionStore, id: string, request: Request): Promise<Response> {
  if (!isSessionId(id)) return fail(400, "invalid session id");
  let patch;
  try {
    patch = parsePatch(JSON.parse(await readBody(request)));
  } catch (error) {
    if (error instanceof TooLarge) return fail(413, "the request body is too large");
    if (error instanceof SyntaxError || error instanceof ValidationError) return fail(400, "invalid session metadata");
    return serverError(`read body for ${id}`, error);
  }
  try {
    const meta = await store.patch(id, patch, new Date());
    return meta ? Response.json(meta) : fail(404, "no such session");
  } catch (error) {
    return serverError(`patch ${id}`, error);
  }
}

export async function deleteSession(store: SessionStore, id: string): Promise<Response> {
  if (!isSessionId(id)) return fail(400, "invalid session id");
  try {
    return (await store.softDelete(id, new Date())) ? new Response(null, { status: 204 }) : fail(404, "no such session");
  } catch (error) {
    return serverError(`delete ${id}`, error);
  }
}
```

- [ ] **Step 4: Run them to see them pass**

Run: `(cd platform/agui/copilotkit-chat && npm test)`
Expected: PASS, `tests 42` (2 + 14 + 17 + 9).

- [ ] **Step 5: The routes** `CHAT/app/api/sessions/route.ts`

```ts
// GET /api/sessions: the session list (lib/api.ts).
import { listSessions } from "../../../lib/api.ts";
import { defaultStore } from "../../../lib/sessions.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET(): Promise<Response> {
  return listSessions(defaultStore());
}
```

`CHAT/app/api/sessions/[id]/route.ts`

```ts
// GET, PATCH and DELETE /api/sessions/{id} (lib/api.ts).
import { deleteSession, getSession, patchSession } from "../../../../lib/api.ts";
import { defaultStore } from "../../../../lib/sessions.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Context = { params: Promise<{ id: string }> };

export async function GET(_request: Request, { params }: Context): Promise<Response> {
  return getSession(defaultStore(), (await params).id);
}

export async function PATCH(request: Request, { params }: Context): Promise<Response> {
  return patchSession(defaultStore(), (await params).id, request);
}

export async function DELETE(_request: Request, { params }: Context): Promise<Response> {
  return deleteSession(defaultStore(), (await params).id);
}
```

- [ ] **Step 6: Attach the recorder to `spe`** — `CHAT/app/api/copilotkit/[[...slug]]/route.ts` becomes

```ts
// CopilotKit runtime (v2, multi-route: /api/copilotkit/info, /api/copilotkit/agent/spe/run, ...).
// The only place that knows the agent's URL and bearer key: both come from server-side
// environment variables (never NEXT_PUBLIC_*) and are sent only to the agent.
import { HttpAgent } from "@ag-ui/client";
import { CopilotRuntime, createCopilotRuntimeHandler } from "@copilotkit/runtime/v2";
import { SessionRecorder } from "../../../../lib/recorder.ts";
import { defaultStore } from "../../../../lib/sessions.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Handler = (request: Request) => Promise<Response>;
let handler: Handler | undefined;

// Built on the first request, not at import: `next build` imports this module without the env.
function getHandler(): Handler {
  if (!handler) {
    const url = process.env.AGENT_URL;
    const key = process.env.AGENT_API_KEY;
    if (!url || !key) {
      throw new Error("AGENT_URL and AGENT_API_KEY must be set");
    }
    const spe = new HttpAgent({ url, headers: { Authorization: `Bearer ${key}` } });
    // Records every run into its session file (lib/recorder.ts); the runtime clones `spe` per
    // request and the clone keeps the recorder.
    spe.use(new SessionRecorder(defaultStore));
    const copilotRuntime = new CopilotRuntime({ agents: { spe } });
    handler = createCopilotRuntimeHandler({ runtime: copilotRuntime, basePath: "/api/copilotkit" });
  }
  return handler;
}

async function handle(request: Request): Promise<Response> {
  try {
    return await getHandler()(request);
  } catch (error) {
    // Details go to the server log only; the browser gets a generic message.
    console.error("copilotkit runtime:", error instanceof Error ? error.message : error);
    return Response.json({ error: "The chat runtime failed; see the chat-ui logs." }, { status: 500 });
  }
}

export { handle as GET, handle as POST, handle as PUT, handle as PATCH, handle as DELETE };
```

- [ ] **Step 7: Type check, then commit**

Run: `(cd platform/agui/copilotkit-chat && npm test && npm run build)`
Expected: tests pass; the route table lists `ƒ /api/copilotkit/[[...slug]]`, `ƒ /api/sessions`,
`ƒ /api/sessions/[id]`; no type error.

```bash
git add platform/agui/copilotkit-chat/lib/api.ts platform/agui/copilotkit-chat/lib/api.test.ts \
  platform/agui/copilotkit-chat/app/api/sessions/route.ts "platform/agui/copilotkit-chat/app/api/sessions/[id]/route.ts" \
  "platform/agui/copilotkit-chat/app/api/copilotkit/[[...slug]]/route.ts"
git commit -s -m "Chat UI: session API and the recorder on the spe agent

GET /api/sessions, GET/PATCH/DELETE /api/sessions/{id}: metadata only,
ids validated before any path, bodies capped at 16 KB, generic error
bodies. Every run through /api/copilotkit is now recorded."
```

### Task 5: volume, image, slow fake run, built-server checks, docs, handoff

**Files:** Modify: `CHAT/Dockerfile`, `CHAT/.dockerignore`, `CHAT/README.md`,
`platform/ansible/roles/agui/templates/docker-compose.yml.j2`, `platform/dev/fake_agent.py`, `AGENTS.md`
(*Running things*, *Current work*), `docs/superpowers/plans/2026-10-29-agui-chat-sessions/README.md` (slices
table status). Create: `CHAT/scripts/check-built-server.mjs`,
`docs/superpowers/plans/2026-10-29-agui-chat-sessions/handoffs/<UTC time>-slice-1-done.md`.

**Interfaces:** Consumes: tasks 1–4. Produces: volume `chat-sessions` at `/data` in `chat-ui` (compose project
`spe-frontend`, so `spe-frontend_chat-sessions`); `/data/sessions` in the image, owned by `node`, mode 0700; the
fake agent's slow run (a user message containing "slow": after its tool call, ten text chunks one second apart,
then the usual answer; `SLOW_STEPS = 10`, `SLOW_STEP_SECONDS = 1.0`), used by slices 2 and 3;
`node scripts/check-built-server.mjs`.

**Decisions:** 1 (the image build, and a first run saved on a fresh volume under the compose hardening: Step 6),
3 (`check-built-server.mjs` check 2: PATCHes overlapping a run's finalisation all land, and the run's messages
too, which needs the queue shared by the session routes and the CopilotKit route), 4 (check 1: two runs at once
keep separate recorder state across clones).

- [ ] **Step 1: Write the built-server check** `CHAT/scripts/check-built-server.mjs`

```js
#!/usr/bin/env node
// Checks the built standalone server (spec §6): what unit tests cannot show because Next.js
// bundles each route separately. Builds nothing: run `npm run build` first. Starts
// platform/dev/fake_agent.py (no model calls) and `node .next/standalone/server.js` with a
// temporary sessions directory and a delayed save, then checks that
//   1. two sessions run at once keep separate recorder state (per-run state across clones);
//   2. PATCHes overlapping a run's finalisation all land, and the run's messages too (one
//      session queue shared by the session routes and the CopilotKit route).
// Exits non-zero on the first failure.
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const chat = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const agentDir = path.resolve(chat, "../pydantic-ai-agent");
const fakeAgent = path.resolve(chat, "../../dev/fake_agent.py");
const AGENT_PORT = 18171;
const UI_PORT = 18172;
const KEY = `check-${randomUUID()}`;
const SAVE_DELAY_MS = 1500;
const ui = `http://127.0.0.1:${UI_PORT}`;
const children = [];

function start(cmd, args, options) {
  const child = spawn(cmd, args, { stdio: ["ignore", "inherit", "inherit"], ...options });
  children.push(child);
  return child;
}

async function waitFor(url) {
  for (let i = 0; i < 300; i++) {
    try {
      await fetch(url);
      return;
    } catch {
      await new Promise((r) => setTimeout(r, 200));
    }
  }
  throw new Error(`${url} did not come up`);
}

function check(ok, what) {
  if (!ok) throw new Error(`FAILED: ${what}`);
  console.log(`ok: ${what}`);
}

function user(content) {
  return { id: randomUUID(), role: "user", content };
}

// One run through the CopilotKit route, read to its end (the SSE stream ends after the save).
async function run(threadId, messages) {
  const response = await fetch(`${ui}/api/copilotkit/agent/spe/run`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ threadId, runId: randomUUID(), messages, tools: [], context: [], state: {}, forwardedProps: {} }),
  });
  const text = await response.text();
  check(response.status === 200 && text.includes("RUN_FINISHED"), `run on ${threadId} finished`);
}

async function session(id) {
  return JSON.parse(await fs.readFile(path.join(dir, `${id}.json`), "utf8"));
}

const dir = await fs.mkdtemp(path.join(os.tmpdir(), "check-sessions-"));
try {
  start("uv", ["run", "--group", "dev", "python", fakeAgent, "--port", String(AGENT_PORT), "--key", KEY], {
    cwd: agentDir, env: { ...process.env, PYDANTIC_AI_NO_BANNER: "1" },
  });
  start("node", [".next/standalone/server.js"], {
    cwd: chat,
    env: {
      ...process.env, PORT: String(UI_PORT), HOSTNAME: "127.0.0.1", AGENT_URL: `http://127.0.0.1:${AGENT_PORT}/agent`,
      AGENT_API_KEY: KEY, SPE_SESSIONS_DIR: dir, SPE_SESSIONS_TEST_SAVE_DELAY_MS: String(SAVE_DELAY_MS),
      NEXT_TELEMETRY_DISABLED: "1", COPILOTKIT_TELEMETRY_DISABLED: "true", DO_NOT_TRACK: "1",
    },
  });
  await waitFor(`http://127.0.0.1:${AGENT_PORT}/`);
  await waitFor(`${ui}/api/sessions`);

  // 1. Two sessions at once.
  const a = randomUUID();
  const b = randomUUID();
  await Promise.all([run(a, [user("first session question")]), run(b, [user("second session question")])]);
  const [ra, rb] = [await session(a), await session(b)];
  check(ra.messages[0].content === "first session question" && rb.messages[0].content === "second session question",
    "each session holds its own conversation");
  check(!JSON.stringify(ra.messages).includes("second session") && !JSON.stringify(rb.messages).includes("first session"),
    "no message crossed between the two sessions");
  check(ra.runs.length === 1 && rb.runs.length === 1 && ra.runs[0].status === "completed" && rb.runs[0].status === "completed",
    "one completed run each");

  // 2. PATCHes, one after another, for as long as a run on the same session is in progress.
  //    The save is delayed by SAVE_DELAY_MS under the queue, so PATCHes sent meanwhile wait for it.
  let ended = false;
  const running = run(a, [...ra.messages, user("second turn")]).finally(() => (ended = true));
  const acknowledged = [];
  const waits = [];
  for (let i = 0; !ended; i++) {
    const t0 = Date.now();
    const response = await fetch(`${ui}/api/sessions/${a}`, {
      method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ title: `patch ${i}` }),
    });
    if (response.status !== 200) throw new Error(`FAILED: PATCH ${i} answered ${response.status}`);
    acknowledged.push(`patch ${i}`);
    waits.push(Date.now() - t0);
  }
  await running;
  check(acknowledged.length > 0, `${acknowledged.length} PATCHes answered 200 during the run`);
  check(waits.some((ms) => ms >= SAVE_DELAY_MS / 2), "a PATCH overlapped the run's finalisation and waited for it");
  const after = await session(a);
  check(after.title === acknowledged.at(-1) && after.title_source === "user", "the last PATCH's title is on disk");
  check(after.runs.length === 2 && after.messages.some((m) => m.content === "second turn"), "the run's messages are on disk");
  console.log("check-built-server: all checks passed");
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
} finally {
  for (const child of children) child.kill("SIGTERM");
  await fs.rm(dir, { recursive: true, force: true });
}
```

- [ ] **Step 2: Run it against the current fake agent**

Run: `(cd platform/agui/copilotkit-chat && npm run build && node scripts/check-built-server.mjs)`
Expected: every line `ok: …`, last `check-built-server: all checks passed`. It needs `uv` and the agent's dev
group (`platform/agui/pydantic-ai-agent`, `uv run --group dev`), ports 18171 and 18172 free, and makes no model
call. If check 2 says `a PATCH overlapped the run's finalisation and waited for it` failed, the queue is not
shared across route bundles: see `shared()` in `lib/sessions.ts` (it must be `globalThis[Symbol.for(…)]`).

- [ ] **Step 3: The slow run in the fake agent** (`platform/dev/fake_agent.py`)

No test covers `fake_agent.py` today (nothing in `platform/agui/pydantic-ai-agent/tests/` or
`platform/dev/tests/` imports it), so it is checked by running it (Step 4). Changes:

The docstring's second paragraph becomes:

```python
The model runs one `run_command` per turn and then answers; a message containing
"fail" makes the model raise, so the run ends in RUN_ERROR; a message containing
"slow" streams its answer in SLOW_STEPS chunks, SLOW_STEP_SECONDS apart (about 10 s),
for stopping, closing or archiving a run in progress. The run log goes to a
temporary directory.
```

Add `import asyncio` above `import json`; below `FIXTURE = …`:

```python

SLOW_STEPS = 10
SLOW_STEP_SECONDS = 1.0
```

and in `scripted`, the `if isinstance(last, ToolReturnPart):` branch becomes:

```python
    if isinstance(last, ToolReturnPart):
        if "slow" in last_user.lower():
            for step in range(1, SLOW_STEPS + 1):
                await asyncio.sleep(SLOW_STEP_SECONDS)
                yield f"Slow step {step} of {SLOW_STEPS}. "
        for chunk in (f"Turn {len(users)}: ", "the command ran. ", "Its output was:\n\n", str(last.content)):
            yield chunk
```

- [ ] **Step 4: Check the slow run by timing it**

```bash
cd platform/agui/pydantic-ai-agent && uv run --group dev python ../../dev/fake_agent.py --port 18181 --key TEST_KEY &
FAKE=$!; sleep 3
S=$(date +%s)
curl -sN -X POST http://127.0.0.1:18181/agent -H 'authorization: Bearer TEST_KEY' \
  -H 'content-type: application/json' -H 'accept: text/event-stream' \
  -d '{"threadId":"t","runId":"r","messages":[{"id":"m1","role":"user","content":"a slow one please"}],"tools":[],"context":[],"state":{},"forwardedProps":{}}' \
  | grep -o '"type":"RUN_[A-Z]*"\|"toolCallName":"run_command"\|Slow step 10 of 10'
echo "$(( $(date +%s) - S )) s"; kill $FAKE; cd -
```

Expected: `"type":"RUN_STARTED"`, `"toolCallName":"run_command"`, `Slow step 10 of 10`, `"type":"RUN_FINISHED"`,
then `10 s` (or 11). Then `(cd platform/agui/pydantic-ai-agent && uv run --group dev pytest -q)` still passes
(Global Constraints: `fake_agent.py` changed).

- [ ] **Step 5: Volume, image, `.dockerignore`**

`platform/ansible/roles/agui/templates/docker-compose.yml.j2`, service `chat-ui`: after `env_file: chat-ui.env`
add

```yaml
    volumes:
      # Chat sessions, one JSON file each (/data/sessions); private like agent-runs.
      - chat-sessions:/data
```

and in the top-level `volumes:` add `  chat-sessions: {}` after `  agent-runs: {}`. `read_only`, the two tmpfs,
`cap_drop`, `security_opt` and the limits stay as they are.

`CHAT/Dockerfile`: after `COPY app ./app` add `COPY lib ./lib`; replace the comment and `RUN install …` above
`USER node` with

```dockerfile
# The image's own files stay root-owned and read-only to the app; only .next/cache is writable,
# and /data, where the chat-sessions volume is mounted: Docker copies /data/sessions, with its
# owner, into the volume when it is first mounted empty, so a fresh volume starts writable.
RUN install -d -o node -g node -m 0700 /app/.next/cache /data /data/sessions
```

`CHAT/.dockerignore` becomes (tests and the test agent stay out of the image; `scripts/` too):

```
*
!package.json
!package-lock.json
!next.config.mjs
!tsconfig.json
!app/
!lib/
lib/*.test.ts
lib/test-*.ts
```

Check the template renders with the volume and the hardening unchanged:

```bash
(cd platform/ansible && uv run -q --with jinja2 --with pyyaml python -c '
import jinja2, yaml
t = jinja2.Template(open("roles/agui/templates/docker-compose.yml.j2").read())
c = yaml.safe_load(t.render(agui_ui_image="ui", agui_agent_image="a", spe_agui_ui_port=3000, spe_agui_agent_port=8100, agui_config_hash="h", spe_frontend_terminal_image="t"))
ui = c["services"]["chat-ui"]
assert ui["volumes"] == ["chat-sessions:/data"] and "chat-sessions" in c["volumes"], ui
assert ui["read_only"] is True and ui["tmpfs"] == ["/tmp", "/app/.next/cache:uid=1000,gid=1000,mode=0700"]
print("compose template: chat-sessions at /data, read_only and tmpfs unchanged")
')
```

Expected: `compose template: chat-sessions at /data, read_only and tmpfs unchanged`.

- [ ] **Step 6: Build the image and save a first run on a fresh volume, hardened**

```bash
(cd platform/agui/copilotkit-chat && docker build -t spe-chat-ui:slice1 .)
(cd platform/agui/pydantic-ai-agent && uv run --group dev python ../../dev/fake_agent.py --port 18181 --key TEST_KEY &)
sleep 3
docker volume create spe-slice1-sessions
docker run -d --name spe-slice1-ui --network host --read-only --tmpfs /tmp \
  --tmpfs /app/.next/cache:uid=1000,gid=1000,mode=0700 --cap-drop ALL --security-opt no-new-privileges:true \
  -v spe-slice1-sessions:/data -e PORT=18182 -e HOSTNAME=127.0.0.1 \
  -e AGENT_URL=http://127.0.0.1:18181/agent -e AGENT_API_KEY=TEST_KEY spe-chat-ui:slice1
for i in $(seq 1 40); do curl -sf http://127.0.0.1:18182/api/sessions && break; sleep 0.5; done; echo
ID=$(python3 -c 'import uuid; print(uuid.uuid4())')
curl -sN -X POST http://127.0.0.1:18182/api/copilotkit/agent/spe/run -H 'content-type: application/json' \
  -d "{\"threadId\":\"$ID\",\"runId\":\"r1\",\"messages\":[{\"id\":\"m1\",\"role\":\"user\",\"content\":\"hello from docker\"}],\"tools\":[],\"context\":[],\"state\":{},\"forwardedProps\":{}}" \
  | grep -o '"type":"RUN_[A-Z]*"'
curl -s http://127.0.0.1:18182/api/sessions; echo
docker exec spe-slice1-ui ls -ln /data /data/sessions
docker rm -f spe-slice1-ui; docker volume rm spe-slice1-sessions
kill "$(lsof -t -i :18181)"   # the fake agent
```

Expected: the first `curl` prints `[]` (the volume starts with an empty, writable `/data/sessions`); the run
prints `"type":"RUN_STARTED"` and `"type":"RUN_FINISHED"`; the list holds one entry with `"title":"hello from
docker"`; `ls -ln` shows `sessions` as `drwx------ 1000 1000` and `<ID>.json` as `-rw------- 1000 1000`. Paste
the output into the PR body.

- [ ] **Step 7: The chat UI's README, *Sessions*** (`CHAT/README.md`)

After the `app/page.tsx` bullet, add the bullet

```markdown
- `lib/`: chat sessions on the server, plain TypeScript that `node --test` runs without Next.js
  (see *Sessions*). `app/api/sessions/` wraps `lib/api.ts`.
```

and after the paragraph on telemetry, a new section:

```markdown
## Sessions

Each conversation is a session: one JSON file, `/data/sessions/<id>.json`, on the `chat-sessions`
volume (mounted at `/data`; the image creates `/data/sessions` owned by `node`). `<id>` is the
AG-UI thread id, a lower-case UUID v4; nothing else ever names a file. The file holds the AG-UI
`messages` as the last run ended with them, one `runs[]` entry per run (`completed`, `failed` or
`cancelled`), and the metadata `title`, `tags`, `pinned`, `hidden` and `deleted_at`.

- `lib/recorder.ts` records every run on the `spe` agent from its AG-UI stream (AG-UI middleware,
  attached with `agent.use()`), whatever its outcome; one run per session at a time. It stores
  messages and run metadata only, never request headers or the agent key.
- `lib/sessions.ts` writes atomically (temporary file, then rename) and one session at a time,
  through a queue on `globalThis` that every route bundle shares. The chat UI is one Node process;
  a second one would need a file lock.
- `/api/sessions`: `GET` lists metadata (newest first, at most 1000, deleted ones left out);
  `GET`/`PATCH`/`DELETE /api/sessions/{id}` read one, change `title`, `tags`, `pinned` or `hidden`
  (bodies up to 16 KB), or mark it deleted. A deleted session's file is kept. There is no `POST`:
  a session exists once its first run is recorded. Errors are `{"error": "<message>"}`.

The files hold whatever participants typed and tools returned, canary values included: treat the
volume like the agent's run log.
```

and after the `docker build` line of the code block, before its closing fence:

```bash
npm test                                      # lib/*.test.ts with node --test (no model, no network)
node scripts/check-built-server.mjs           # after npm run build: the built server against fake_agent.py
```

`No persistence: a reload starts a new conversation.` stays: the page does not open sessions until slice 2.

- [ ] **Step 8: `AGENTS.md`, *Running things*; the canary ladder's isolation**

In `AGENTS.md`, *Running things*, after the `(cd platform/agui/copilotkit-chat && npm ci && npm run build)`
line add:

```bash
(cd platform/agui/copilotkit-chat && npm ci && npm test)               # chat UI (sessions, recorder, API)
```

The canary ladder's `isolation.NOT_RESTORED` (spec, *Inputs for the plan*): run
`git ls-tree origin/main platform/promptfoo-evals/isolation.py`. On 2026-10-30 it prints nothing (the ladder's
slice 2 has not merged), so this slice changes nothing there; that slice's task text already names
`spe-frontend_chat-sessions`. If it prints a file, add `"spe-frontend_chat-sessions"` to `NOT_RESTORED` in it,
run `(cd platform/promptfoo-evals && uv run --group dev pytest -q)`, and stage it with this step's commit.

- [ ] **Step 9: Run every suite, then commit**

```bash
(cd platform/agui/copilotkit-chat && npm ci && npm test && npm run build && node scripts/check-built-server.mjs)
uv run --with pytest pytest platform/dev/tests -q
(cd platform/agui/pydantic-ai-agent && uv run --group dev pytest -q)
python3 .methodology/shared/sync-agents.py --check
```

Expected: `tests 42`, `fail 0`; `all checks passed`; both pytest runs pass; `sync-agents.py --check` exits 0.

```bash
git add platform/agui/copilotkit-chat/Dockerfile platform/agui/copilotkit-chat/.dockerignore \
  platform/agui/copilotkit-chat/README.md platform/agui/copilotkit-chat/scripts/check-built-server.mjs \
  platform/ansible/roles/agui/templates/docker-compose.yml.j2 platform/dev/fake_agent.py AGENTS.md
git commit -s -m "Chat UI: sessions volume, lib/ in the image, built-server check, slow fake run

chat-ui mounts the chat-sessions volume at /data; the image creates
/data/sessions owned by node so a fresh volume starts writable under
read_only. check-built-server.mjs runs the built server against
fake_agent.py: per-run recorder state across clones, and one session
queue shared by the session routes and the CopilotKit route."
```

- [ ] **Step 10: Hand off, open the PR for review**

1. Write `docs/superpowers/plans/2026-10-29-agui-chat-sessions/handoffs/$(date -u +%Y-%m-%dT%H%MZ)-slice-1-done.md`
   (`# <YYYY-MM-DD>: slice 1 done`), run `date -u` for the name: what merged in this PR, the commands run and
   their results (test count, `check-built-server` output, the Step 6 output), every ruling (*decision, why,
   cost if wrong*), any gotcha met (written as a `docs/knowledge/` note and linked, per `AGENTS.md`, *Project
   knowledge*: at least "`node --test lib/` fails on Node 24; pass the glob `'lib/*.test.ts'`"), and the next
   unit: slice 2/3, `impl/agui-chat-sessions-2-sidebar`, file `slice-2-sidebar.md`.
2. In the plan's `README.md`, *PR slices*, slice 1's status → `merged #<this PR>`.
3. In `AGENTS.md`, *Current work*, the AG-UI chat sessions line → `**Next: slice 2/3**
   \`impl/agui-chat-sessions-2-sidebar\``, handoff pointer unchanged.
4. Commit those three (`git commit -s -m "Slice 1 of AG-UI chat sessions: handoff"`), push, mark the PR ready
   (`gh pr ready <n> --repo thodkatz/elixir-biohackathon-2026-test`), and run the local review round
   (`AGENTS.md`, *Reviewers*). The PR body lists what ran (*Overrides*: the checks before a merge) and the Step 6
   output. The user merges (`AGENTS.md`, *Overrides*); slice 2 starts after that.
