// When the page fetches the session list on its own (spec §6 *Refresh*): besides load, run ends and metadata
// changes, on `visibilitychange` (visible) and `focus`, and every POLL_MS while the list shows a session
// running that no holder in this page streams (a run from another tab, or from before a reload), until it
// shows none. Pure: no React, no clock.
import { runningIds } from "./live-sessions.ts";
import type { Live } from "./live-sessions.ts";
import type { SessionMeta } from "./sessions.ts";

export const POLL_MS = 2000;

/** True while the list shows a session running that no holder in the page streams. */
export function needsPoll(list: readonly SessionMeta[], live: Live): boolean {
  for (const id of runningIds(list, live)) if (!live.streaming.has(id)) return true;
  return false;
}
