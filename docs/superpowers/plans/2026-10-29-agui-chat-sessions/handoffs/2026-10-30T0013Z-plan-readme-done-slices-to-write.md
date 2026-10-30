# 2026-10-30: plan README done, the three slice files still to write

Mid-unit handoff (`sessions-and-context.md`, *Handing off mid-unit*) of the plan unit, PR #8
(`plan/agui-chat-sessions`, draft, worktree `/workspace/biohackathon/wt-agui-plan`). The session that wrote
the README went past its context budget; three slice-writer subagents it had dispatched were stopped with
it and wrote nothing.

**State.**

- Committed: the plan's `README.md` (goal, global constraints, *Shared interfaces*, file structure, PR
  slices, Review Focus, proposed spec clarification 1), the `AGENTS.md` *Current work* line (names slice 1/3,
  to be true once #8 merges) and the `docs/README.md` row. `origin/main` (methodology `15c1cb5`) is merged in.
- Not written: `slice-1-store.md`, `slice-2-sidebar.md`, `slice-3-complete.md`, which the README's slices table
  already links.

**Next task.** Write the three slice files, then the review round, then hand off (below). Dispatch one
writer subagent per slice in parallel (`AGENTS.md`, *Spawn subagents freely*), each told to: write only its
own file, never commit; read the README (its *Shared interfaces* are binding), the spec, the writing-plans skill
(`superpowers:writing-plans`; house style: the first ~80 lines of
`docs/superpowers/plans/2026-10-22-canary-eval-ladder/slice-1-scoring.md`), and the code it changes; try the
critical code in a scratch directory (`node_modules` to copy: the main checkout's
`platform/agui/copilotkit-chat/node_modules/`) and say in the file what was run; ≤ 5 tasks, full TDD steps,
complete code, exact commands, commit steps with `git commit -s`; return a summary of ≤ 250 words with any
name it needed beyond the README. The task list each writer gets is the README's slices row plus:

- **Slice 1** (decisions 1–8, 13): (1) the clone gate: `npm test` (`node --test lib/`),
  `allowImportingTsExtensions`, `rxjs` 7.8.1 listed, `lib/clone.test.ts` with an in-test AG-UI SSE server: the
  middleware survives `clone()`, two clones keep separate per-run state, and `abortRun()` reaches the middleware
  as `RUN_ERROR` `code: "abort"`; it is a feasibility gate (spec, *Inputs for the plan*); same task adds
  clarification 1 to the spec. (2) `lib/sessions.ts` with Review Focus 1–3. (3) `lib/recorder.ts`: every
  termination row, refusals (also when `shared().closing`), the save-failed event, decision 13's two keys,
  `RunHandle.cancel()`, and the test-only `SPE_SESSIONS_TEST_SAVE_DELAY_MS` that slice 3 uses. (4) `lib/api.ts`,
  the routes, `agent.use(...)` in the CopilotKit route, Review Focus 4. (5) Dockerfile, `.dockerignore`, compose
  volume, the slow run in `fake_agent.py`, `scripts/check-built-server.mjs`, `docker build` plus a hardened run on
  a fresh volume, the chat-UI README's *Sessions* (store and API only), `AGENTS.md` *Running things*, the
  `isolation.NOT_RESTORED` step only if `platform/promptfoo-evals/isolation.py` is on `main` by then (it is not
  today), then the slice's handoff.
- **Slice 2** (early output): (1) open/new/`?session=` (Review Focus 5), first checking how CopilotChat 1.79
  reacts to a changed `threadId` with `agent.setMessages()`; `app/sidebar.tsx` list. (2) the row menu. (3)
  `lib/shutdown.ts` and `instrumentation.ts`, checked against the standalone server within `stop -t 30`. (4) the
  archive export (barrier), `write.yml`, `write_agui_run.py`, the `fence()` change, the tests. (5) the stale docs
  of spec §3 and §4, the Playwright run (three sessions, screenshots), `archive.yml` on the dev VM, the PR body
  sample, the handoff.
- **Slice 3**: pure helpers in `lib/sidebar-view.ts` (search, tag filter, date groups, tag counts) and their
  integration, the chat header, disabled controls, the reconciliation (with the save delay), `checks.yml`
  (decisions 13 and 15), the dev-VM archive checks of decision 11 (the `destroy.yml` part must not run
  `destroy.yml` against the dev VM unless the user agrees at that step), the paid check behind the user's OK,
  and the last slice's cleanup (*Current work* line removed).

**Verified facts for the writers** (read in the installed packages; cite them):

- `@ag-ui/client` 1.0.2 exports `Middleware` (`run(input, next)`, protected `runNextWithState`, which yields
  `{event, messages, state}` after each event) and re-exports `@ag-ui/core`; `use()` adds middlewares and
  `clone()` copies them. Observable is rxjs 7.8.1.
- `@copilotkit/runtime` 1.79 `handle-run.mjs`: `cloneAgentForRequest` = `agents[id].clone()` per request, then
  `setMessages(input.messages)`, `threadId = input.threadId`. The in-memory runner (`runner/in-memory.mjs`) runs
  `runAgent()` detached from the client, throws "Thread already running" for a second concurrent run of a
  thread, and its `stop()` calls `agent.abortRun()`.
- `HttpAgent.abortRun()` aborts the fetch; the HTTP transform turns the `AbortError` into `RUN_ERROR`
  `{code: "abort"}` rather than ending the stream (README, *Proposed spec clarifications*, 1).

**After the slice files.** Self-review against the spec (writing-plans checklist), and copy any new names the
writers report into the README's *Shared interfaces*. Then commit, mark #8 ready, and run the local review round
(`AGENTS.md`, *Reviewers*; codex and agy were the user's reviewer choice for the spec and may be used again, or
reviewer subagents with the correctness and methodology focuses). Address the findings and post one reply comment.
Then hand off. **Merging #8:** per `AGENTS.md`, *Overrides*, the user merges every PR. On 2026-10-29 the user
asked to "proceed with the implementation auto continue", but #8 still waits for their merge. Slice 1 starts
only after #8 is on `main`.

**Resume:**

```bash
cd /workspace/biohackathon/wt-agui-plan && git status && git log --oneline -5
ls docs/superpowers/plans/2026-10-29-agui-chat-sessions/handoffs | tail -1   # this file
python3 .methodology/shared/sync-agents.py --check                          # exits 0
gh pr view 8 -R thodkatz/elixir-biohackathon-2026-test --json isDraft,state
```
