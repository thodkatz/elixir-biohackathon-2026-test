# 2026-10-29: a new `spe-frontend` volume, `chat-sessions` (from the AG-UI chat sessions spec, PR #7)

**Change.** The AG-UI chat sessions spec (`docs/superpowers/specs/2026-10-29-agui-chat-sessions-design.md`)
adds the named volume `chat-sessions` to `roles/agui/templates/docker-compose.yml.j2`, mounted at `/data` in
`chat-ui` only. It is added by that track's slice 1. Evaluations call the agent directly, never `chat-ui`, so
the volume is **not restored** between cases.

**Tasks rewritten in PR #7** (review finding M1 there):

- `slice-2-isolation.md`, the *Names fixed by this slice* table and task 2, step 3: `NOT_RESTORED` holds
  `spe-frontend_chat-sessions` when the template on `main` declares it, so
  `test_volumes_match_the_compose_templates` passes whichever track lands first.
- Spec part `05-isolation.md`, *Mutable state*: a row for the chat sessions.

If this slice lands first, the chat sessions track's slice 1 adds the entry to `isolation.NOT_RESTORED`
itself (its spec, *Inputs for the plan*). Nothing else in this plan changes; the next unit is still the one the
previous handoff names.
