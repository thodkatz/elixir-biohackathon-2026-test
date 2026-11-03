# AG-UI agent and CopilotKit frontend for SPE instances — design

Date: 2026-10-15 · Branch: `agent-agui-frontend` (from `dd14684`) · Status: draft for review;
implemented on `agent-agui-frontend-impl` — §12 records what implementation verified and changed

Context and reasoning: the biohackathon knowledge repository, records 0001–0005
(0005 is the playground this is sub-project 1 of).

## Parts

| File | What it contains | Read when |
|---|---|---|
| [`01-goal.md`](01-goal.md) | §1 Goal: what an instance runs with `spe_frontend: agui`, and what success means | you need the purpose |
| [`02-non-goals.md`](02-non-goals.md) | §2 Non-goals | you wonder whether something is in scope |
| [`03-architecture.md`](03-architecture.md) | §3 Architecture: the three containers, the key boundary, why the agent needs a bearer key | you change what a container holds or who talks to whom |
| [`04-layout.md`](04-layout.md) | §4 Layout in the repository | you look for where a piece lives |
| [`05-agent-service.md`](05-agent-service.md) | §5 The agent service: endpoints, model, tools, prompt, limits, run log, configuration, history | you change the agent |
| [`06-chat-ui.md`](06-chat-ui.md) | §6 The chat UI | you change the chat UI |
| [`07-ansible.md`](07-ansible.md) | §7 Ansible: existing-VM provisioning, the development VM, variables, the `agui` role, compose, handoff | you change how an instance is built |
| [`08-error-handling.md`](08-error-handling.md) | §8 Error handling and known gaps | you handle a failure or look for a known gap |
| [`09-checks.md`](09-checks.md) | §9 Checks (role end and `verify.yml`) | you change the checks |
| [`10-testing.md`](10-testing.md) | §10 Testing: agent unit tests, chat UI, promptfoo | you write or run tests |
| [`11-verify-during-implementation.md`](11-verify-during-implementation.md) | §11 Things to verify during implementation | you check what was open when this was built |
| [`12-implementation-findings.md`](12-implementation-findings.md) | §12 Implementation findings (2026-10-15): versions, §11 settled, behaviour made precise, observed results | you need what implementation verified |
