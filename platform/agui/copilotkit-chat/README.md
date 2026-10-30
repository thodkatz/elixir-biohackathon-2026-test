# SPE chat UI

Next.js 16.4.1 + CopilotKit 1.79.0 (v2 API), a thin client for the SPE agent.

- `app/api/copilotkit/[[...slug]]/route.ts`: `CopilotRuntime` (`@copilotkit/runtime/v2`) in
  multi-route mode (`/api/copilotkit/info`, `/api/copilotkit/agent/spe/run`, …) via
  `createCopilotRuntimeHandler({ basePath: "/api/copilotkit" })`, with one agent `spe`: an
  `HttpAgent` (`@ag-ui/client` 1.0.2) for `AGENT_URL` sending `Authorization: Bearer
  $AGENT_API_KEY`. Both variables are server-side only (not `NEXT_PUBLIC_*`) and read on the
  first request, so the build needs neither.
- `app/page.tsx`: full-screen `CopilotChat` (`@copilotkit/react-core/v2`); every tool call is a
  collapsible card (`useDefaultRenderTool`) with name, status, arguments and the first 40 lines
  or 4000 characters of the result, rendered as text. Run errors appear in a bar above the chat.
  No persistence: a reload starts a new conversation.
- `lib/`: chat sessions on the server, plain TypeScript that `node --test` runs without Next.js
  (see *Sessions*). `app/api/sessions/` wraps `lib/api.ts`.

Telemetry is off in the image: `NEXT_TELEMETRY_DISABLED=1`, `COPILOTKIT_TELEMETRY_DISABLED=true`,
`DO_NOT_TRACK=1` (the runtime's `/info` then tells the browser client the same).

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

```bash
npm ci && npm run build                       # type-checks too
# against the scripted agent (no LLM): in ../pydantic-ai-agent
#   uv run --group dev python ../../dev/fake_agent.py --port 18100 --key TEST_KEY
AGENT_URL=http://127.0.0.1:18100/agent AGENT_API_KEY=TEST_KEY PORT=3000 node .next/standalone/server.js
#   (copy .next/static to .next/standalone/.next/static first; the Dockerfile does)
docker build -t spe-chat-ui .                 # node:24-slim, user node, port 3000
npm test                                      # lib/*.test.ts with node --test (no model, no network)
node scripts/check-built-server.mjs           # after npm run build: the built server against fake_agent.py
```

The image runs with a read-only root filesystem when `/tmp` and `/app/.next/cache` are tmpfs
(uid 1000), with `cap_drop: ALL` and `no-new-privileges`.

TypeScript is pinned to 6.0.3: TypeScript 7 has no JavaScript API, which `next build` uses for its
type check.
