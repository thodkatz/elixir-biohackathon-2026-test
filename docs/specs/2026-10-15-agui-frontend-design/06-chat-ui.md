## 6. The chat UI

- Next.js app, two parts:
  - `app/page.tsx`: full-screen `<CopilotChat>` wired to agent `spe`.
  - `app/api/copilotkit/[[...slug]]/route.ts` (catch-all; implementation
    finding, §12): `CopilotRuntime` (`@copilotkit/runtime/v2`)
    with `agents: { spe: new HttpAgent({ url: AGENT_URL, headers: { Authorization: … } }) }`
    (`@ag-ui/client`).
- **Tool calls are rendered** with `useDefaultRenderTool`
  (`@copilotkit/react-core/v2`, verified in CopilotKit docs 2026-10-15): one
  collapsible card per call showing the tool name, its arguments (for
  `run_command`, the command), status, and the first lines of the result.
- No secrets in the browser; sessions are kept on the server
  (`platform/agui/copilotkit-chat/README.md`, *Sessions*).
- Exact package versions are pinned in `package-lock.json`; the image runs
  `next start` as a non-root user.
