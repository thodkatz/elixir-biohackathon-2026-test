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
