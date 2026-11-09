// One session's runs, on that session's own agent (app/session-agent.tsx): after each run, however it ended,
// the list is fetched until it shows that run, or the error bar says it was not saved. A run the recorder
// ended itself (a refusal, or a journal it could not write: its RUN_ERROR is already in the bar) is fetched
// once, without retries: nothing more is written for it. `onStarted` hears each run as it starts, for a New
// chat's title; `onRecorded` once the list shows the run; `onEnded` last, once the list (or its error) has
// been passed on, so the page drops the agent only after it has seen that list. `onEnded` is for the latest
// run only: a run started before the previous one's list came back keeps the session streaming, and the
// page must not drop its agent. A rejoined run (a connect to a run already going, lib/rejoin.ts) has a start
// the page does not know, so its end waits for the list to show the session not running instead
// (waitNotRunning); a list without the session is the session deleted, which the page's list handling deals
// with, not an error bar. Pure apart from the agent, so `node --test` covers it.
import type { SessionMeta } from "./sessions.ts";
import { SAVE_FAILED_MESSAGE, isRefusal, reconcile, waitNotRunning } from "./reconcile.ts";
import type { FetchList } from "./reconcile.ts";

export type RunWatchOptions = {
  id: string;
  /** The page's list fetch, stamped with its order (lib/list-order.ts). */
  fetchList: FetchList;
  onList: (list: SessionMeta[]) => void;
  onError: (message: string) => void;
  onStarted: (id: string) => void;
  onRecorded: (id: string) => void;
  onEnded: (id: string) => void;
};

/** The part of an AG-UI agent this needs. */
export type RunSource = {
  subscribe(s: {
    onRunInitialized?: () => void;
    onRunErrorEvent?: (p: { event: { message?: unknown } }) => void;
    onRunFinalized?: () => void;
  }): { unsubscribe(): void };
};

type Run = { startMs: number; refused: boolean; rejoined: boolean };

export const LIST_FAILED = "The session list could not be loaded.";

/** `opts` is read at each event, so the caller may pass its latest props. */
export function watchRuns(agent: RunSource, opts: () => RunWatchOptions, now: () => number = Date.now) {
  let current: Run | null = null; // the run in progress
  let last: Run | null = null; // the latest run, in progress or ended
  let rejoining = false; // a connect is under way: the next run to start is the one it rejoins
  const sub = agent.subscribe({
    onRunInitialized: () => {
      current = last = { startMs: now(), refused: false, rejoined: rejoining };
      rejoining = false;
      opts().onStarted(opts().id);
    },
    onRunErrorEvent: ({ event }) => {
      if (current !== null && isRefusal(String(event.message ?? ""))) current.refused = true;
    },
    onRunFinalized: () => {
      const ended = current;
      current = null;
      if (ended === null) return;
      const { id } = opts();
      // Only the latest run ends the session: a newer one started since keeps it streaming.
      const done = () => { if (last === ended) opts().onEnded(id); };
      if (ended.refused) {
        opts().fetchList()
          .then(({ list }) => opts().onList(list))
          .catch(() => opts().onError(LIST_FAILED))
          .finally(done);
        return;
      }
      if (ended.rejoined) {
        waitNotRunning(opts().fetchList, id)
          .then(({ list, saved }) => {
            opts().onList(list);
            if (!list.some((s) => s.id === id)) return; // deleted: the list's own handling, no error bar
            if (saved) opts().onRecorded(id);
            else opts().onError(SAVE_FAILED_MESSAGE);
          })
          .catch(() => opts().onError(LIST_FAILED))
          .finally(done);
        return;
      }
      reconcile(opts().fetchList, id, ended.startMs)
        .then(({ list, saved }) => {
          opts().onList(list);
          if (saved) opts().onRecorded(id);
          else opts().onError(SAVE_FAILED_MESSAGE);
        })
        .catch(() => opts().onError(LIST_FAILED))
        .finally(done);
    },
  });
  return {
    unsubscribe: () => sub.unsubscribe(),
    /** Pass every run error here too: a refusal that reaches the page outside the stream (a failed request
     *  rather than a RUN_ERROR event) is then not reported as a failed save. */
    /** Just before a connect: the run it starts is a rejoined one. */
    rejoining: () => { rejoining = true; },
    /** Once the connect has ended, however: a connect that never started a run leaves no mark on the next. */
    rejoined: () => { rejoining = false; },
    noteRunError: (message: string) => {
      if (last !== null && isRefusal(message)) last.refused = true;
    },
  };
}
