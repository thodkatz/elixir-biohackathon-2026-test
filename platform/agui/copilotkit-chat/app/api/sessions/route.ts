// GET /api/sessions: the session list (lib/api.ts).
import { listSessions } from "../../../lib/api.ts";
import { defaultStore } from "../../../lib/sessions.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET(): Promise<Response> {
  return listSessions(defaultStore());
}
