"use client";
// THROWAWAY (slice 1 of the leave-running-chat plan, ruling 2; removed in its task 3): decision 42's rejoin
// check. `?a=<id>&b=<id>&mode=stream|open|rejoin` mounts one holder per id, each with a private agent
// (thread-scoped useAgent) and its own CopilotChat. stream: an empty history; open: the journal's history
// (GET /api/sessions/{id}) set on the agent, no connect; rejoin: the same, then connectAgent when GET answers
// `running`. `&dedupe=1` (step 4): on each message change while the connect lasts, and once after it resolves, the
// agent's messages are set to rejoinedMessages(history, agent.messages); `&dedupe=wait`: the same, but only from
// the replay's first event on (connectAgent's setMessages([]) is left to show). Driven by docs/superpowers/plans/2026-11-08-agui-leave-running-chat/evidence/slice-1/rejoin_check.py.
import {
  CopilotChat,
  CopilotChatConfigurationProvider,
  CopilotKitCoreRuntimeConnectionStatus,
  CopilotKitProvider,
  useAgent,
  useCopilotKit,
} from "@copilotkit/react-core/v2";
import type { Message } from "@ag-ui/client";
import { useEffect, useState } from "react";
import { fetchSession } from "../../lib/client.ts";

type Mode = "stream" | "open" | "rejoin";
type Dedupe = "off" | "every" | "wait";

// Slice 3's lib/rejoin.ts rule, inlined: keep the history; drop a later message whose id the history already
// holds, unless it belongs to the current run, whose copy replaces the history's partial one in place.
function rejoinedMessages(history: Message[], messages: Message[], current: Set<string>): Message[] {
  const byId = new Map(messages.map((m) => [m.id, m]));
  const held = new Set(history.map((m) => m.id));
  const kept = history.map((h) => (current.has(h.id) && byId.has(h.id) ? byId.get(h.id)! : h));
  return [...kept, ...messages.filter((m) => !held.has(m.id))];
}

function Holder({ id, mode, dedupe }: { id: string; mode: Mode; dedupe: Dedupe }) {
  // Thread-scoped: first a provisional agent (isReady false), then the registered private one.
  const { agent, isReady } = useAgent({ agentId: `spe-${id}`, runtimeAgentId: "spe", threadId: id });
  const { copilotkit } = useCopilotKit();
  const [ids, setIds] = useState<string[]>([]);
  const [status, setStatus] = useState("waiting");

  // The ids the agent holds, on every change.
  useEffect(() => {
    if (!isReady) return;
    const sync = () => setIds(agent.messages.map((m) => m.id));
    sync();
    const sub = agent.subscribe({ onMessagesChanged: sync });
    return () => sub.unsubscribe();
  }, [agent, isReady]);

  // Every committed list of ids, for the script (window.__rejoinTrace[id]): what the 1 s ticks miss.
  useEffect(() => {
    const w = window as unknown as { __rejoinTrace?: Record<string, { t: number; status: string; ids: string[] }[]> };
    w.__rejoinTrace ??= {};
    (w.__rejoinTrace[id] ??= []).push({ t: Date.now(), status, ids });
  }, [id, ids, status]);

  // Keyed on the agent object: messages set on the provisional one would be lost.
  useEffect(() => {
    if (!isReady) return;
    if (mode === "stream") {
      setStatus("ready");
      return;
    }
    let live = true;
    void (async () => {
      const session = await fetchSession(id);
      if (!live) return;
      agent.setMessages(session?.messages ?? []);
      if (mode === "rejoin" && session?.running) {
        setStatus(dedupe === "off" ? "connecting" : `connecting dedupe ${dedupe}`);
        if (dedupe === "off") {
          await copilotkit.connectAgent({ agent });
          if (live) setStatus("connect-resolved");
          return;
        }
        const history = session.messages;
        // The message ids the replay's events name since its last RUN_STARTED (the current run's).
        let current = new Set<string>();
        // connectAgent clears the agent's messages (setMessages([])) and then starts its event pipeline from a
        // copy of whatever the agent holds (@ag-ui/client apply/default.ts, `structuredClone_(agent.messages)`).
        // `every` merges on that clear too, so the history is back before React commits the empty list; were
        // the merge to land before the pipeline's copy, the history's partial copy of the current run would sit
        // under the replay's deltas (whether it does is a microtask race: the script's slow-step count shows it).
        // `wait` merges only from the replay's first event on, and leaves the empty list to show.
        let streaming = dedupe === "every";
        let merges = 0;
        const merge = () => {
          if (!streaming) return;
          const next = rejoinedMessages(history, agent.messages, current);
          if (JSON.stringify(next) === JSON.stringify(agent.messages)) return;
          merges += 1;
          agent.setMessages(next);
        };
        const sub = agent.subscribe({
          onEvent: ({ event }) => {
            streaming = true;
            if (event.type === "RUN_STARTED") current = new Set();
            const e = event as { messageId?: unknown; parentMessageId?: unknown };
            if (typeof e.messageId === "string") current.add(e.messageId);
            if (typeof e.parentMessageId === "string") current.add(e.parentMessageId);
          },
          onMessagesChanged: merge,
        });
        try {
          await copilotkit.connectAgent({ agent });
        } finally {
          sub.unsubscribe();
        }
        merge();
        if (live) setStatus(`connect-resolved dedupe ${dedupe} merges=${merges}`);
      } else {
        setStatus(session ? `opened running=${session.running}` : "opened 404");
      }
    })().catch((e: unknown) => {
      if (live) setStatus(`error ${e instanceof Error ? e.message : String(e)}`);
    });
    return () => {
      live = false;
    };
  }, [agent, isReady, mode, dedupe, id, copilotkit]);

  return (
    <section data-testid={`holder-${id}`} style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", border: "1px solid #888" }}>
      <div style={{ fontSize: 11 }}>
        <span data-testid={`status-${id}`}>{status}</span> · <span data-testid={`running-${id}`}>{String(agent.isRunning)}</span>
      </div>
      <pre data-testid={`ids-${id}`} style={{ fontSize: 10, whiteSpace: "pre-wrap", maxHeight: 80, overflow: "auto" }}>
        {JSON.stringify(ids)}
      </pre>
      {isReady ? (
        <div data-testid={`chat-${id}`} style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
          <CopilotChatConfigurationProvider agentId={`spe-${id}`} threadId={id} hasExplicitThreadId={false}>
            <CopilotChat key={id} agentId={`spe-${id}`} />
          </CopilotChatConfigurationProvider>
        </div>
      ) : (
        <div>agent not ready</div>
      )}
    </section>
  );
}

// Unmounts and remounts its holder (a new key), so its private agent is unregistered and registered again.
function Remountable({ id, mode, dedupe }: { id: string; mode: Mode; dedupe: Dedupe }) {
  const [generation, setGeneration] = useState(0);
  return (
    <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
      <button type="button" data-testid={`remount-${id}`} onClick={() => setGeneration((g) => g + 1)}>
        remount {id.slice(0, 8)} (generation <span data-testid={`generation-${id}`}>{generation}</span>)
      </button>
      <Holder key={`${id}-${generation}`} id={id} mode={mode} dedupe={dedupe} />
    </div>
  );
}

function dedupeOf(raw: string | null): Dedupe {
  return raw === "1" ? "every" : raw === "wait" ? "wait" : "off";
}

function Holders() {
  const { copilotkit } = useCopilotKit();
  const [params, setParams] = useState<{ ids: string[]; mode: Mode; dedupe: Dedupe } | null>(null);
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const raw = q.get("mode");
    const mode: Mode = raw === "open" || raw === "rejoin" ? raw : "stream";
    setParams({ ids: [q.get("a"), q.get("b")].filter((x): x is string => !!x), mode, dedupe: dedupeOf(q.get("dedupe")) });
  }, []);
  const connected = copilotkit.runtimeConnectionStatus === CopilotKitCoreRuntimeConnectionStatus.Connected;
  if (!params || !connected) return <div data-testid="page-status">runtime {copilotkit.runtimeConnectionStatus}</div>;
  return (
    <div style={{ display: "flex", gap: 8, height: "100vh" }} data-testid="page-status-ready">
      {params.ids.map((id) => (
        <Remountable key={id} id={id} mode={params.mode} dedupe={params.dedupe} />
      ))}
    </div>
  );
}

export default function Page() {
  return (
    <CopilotKitProvider runtimeUrl="/api/copilotkit" showDevConsole={false}>
      <Holders />
    </CopilotKitProvider>
  );
}
