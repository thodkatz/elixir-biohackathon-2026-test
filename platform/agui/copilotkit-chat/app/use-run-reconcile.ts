// One session's runs, on that session's own agent (./session-agent.tsx): after each run, however it ended,
// the list is fetched until it shows that run, or the error bar says it was not saved. A run the recorder
// ended itself (a refusal, or a journal it could not write: its RUN_ERROR is already in the bar) is fetched
// once, without retries: nothing more is written for it. `onStarted` hears each run as it starts, for a New
// chat's title; `onRecorded` once the list shows the run; `onEnded` last, once the list (or its error) has
// been passed on, so the page drops the agent only after it has seen that list.
import type { AbstractAgent } from "@copilotkit/react-core/v2";
import { useCallback, useEffect, useRef } from "react";
import type { SessionMeta } from "../lib/sessions.ts";
import { SAVE_FAILED_MESSAGE, isRefusal, reconcile } from "../lib/reconcile.ts";
import type { FetchList } from "../lib/reconcile.ts";

type Options = {
  id: string;
  /** The page's list fetch, stamped with its order (lib/list-order.ts). */
  fetchList: FetchList;
  onList: (list: SessionMeta[]) => void;
  onError: (message: string) => void;
  onStarted: (id: string) => void;
  onRecorded: (id: string) => void;
  onEnded: (id: string) => void;
};
type Run = { startMs: number; refused: boolean };

const LIST_FAILED = "The session list could not be loaded.";

export function useRunReconcile(agent: AbstractAgent, opts: Options) {
  const latest = useRef(opts);
  latest.current = opts;
  const current = useRef<Run | null>(null); // the run in progress
  const last = useRef<Run | null>(null); // the latest run, in progress or ended

  useEffect(() => {
    const sub = agent.subscribe({
      onRunInitialized: () => {
        current.current = last.current = { startMs: Date.now(), refused: false };
        latest.current.onStarted(latest.current.id);
      },
      onRunErrorEvent: ({ event }) => {
        const run = current.current;
        if (run !== null && isRefusal(String(event.message ?? ""))) run.refused = true;
      },
      onRunFinalized: () => {
        const ended = current.current;
        current.current = null;
        if (ended === null) return;
        const { id } = latest.current;
        const done = () => latest.current.onEnded(id);
        if (ended.refused) {
          latest.current.fetchList()
            .then(({ list }) => latest.current.onList(list))
            .catch(() => latest.current.onError(LIST_FAILED))
            .finally(done);
          return;
        }
        reconcile(latest.current.fetchList, id, ended.startMs)
          .then(({ list, saved }) => {
            latest.current.onList(list);
            if (saved) latest.current.onRecorded(id);
            else latest.current.onError(SAVE_FAILED_MESSAGE);
          })
          .catch(() => latest.current.onError(LIST_FAILED))
          .finally(done);
      },
    });
    return () => sub.unsubscribe();
  }, [agent]);

  /** Pass every run error here too: a refusal that reaches the page outside the stream (a failed request
   *  rather than a RUN_ERROR event) is then not reported as a failed save. */
  const noteRunError = useCallback((message: string) => {
    if (last.current !== null && isRefusal(message)) last.current.refused = true;
  }, []);

  return { noteRunError };
}
