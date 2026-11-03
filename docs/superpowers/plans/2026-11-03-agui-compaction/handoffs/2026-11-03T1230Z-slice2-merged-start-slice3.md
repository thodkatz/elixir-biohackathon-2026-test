# 2026-11-03: slice 2/3 done (PR #18); start slice 3/3

Slice 2 showed a compaction to the user: the divider in the chat (live and after a reload, light and dark), the
fake agent's `compact`, the archive's `## Compacted` and `Compactions` column, and a dev VM session on Haiku that
compacted. After the final fix wave: chat `npm test` 102 passed, `npm run build` clean, `platform/dev/tests` 77
passed, agent suite 185 passed (final review), e2e `--scenario compaction` ok. Final review: no blockers; what
it found and what stayed deferred is in PR #18's review comment.

## Next: slice 3/3, `impl/agui-compaction-3-denbi-docs`

From `main` after #18 merged: claim (branch, draft PR `… (3/3)`), a worktree, then
[`slice-3-denbi-docs.md`](../slice-3-denbi-docs.md) with `superpowers:subagent-driven-development`.

- **The dev VM keeps `spe_agent_context_window_tokens: 20000`** in the main checkout's `dev-local.yml` (task 5,
  step 4): slice 3's decision 13 check reuses it. Put it back when slice 3 says so.
- **Deploying a worktree:** `-e spe_agui_source_dir=<worktree>/platform/agui`, not the worktree root
  ([`agui-source-dir.md`](../../../../knowledge/agui-source-dir.md)); also `-e spe_min_free_gb=5` and the LLM key
  ([`dev-vm-converge.md`](../../../../knowledge/dev-vm-converge.md)).
- **The live prompt must forbid pipes**: Haiku ran `seq 1 3000 | tail -n 1` for "tell me only the last line" and
  never compacted (`4f1dd7e`); slice 3's step 2 already uses the fixed wording.
- **One turn can compact more than once**: expect `Compactions` ≥ 1 and check each `compactions` entry.
- **Archive gap:** once #18 merged, `main`'s `archive.yml` renders `## Compacted`; before that, re-render with the
  branch's `write_agui_run.py <run dir> <run dir>` (as slice 2 did).
- Waiting on the user: clarification 5 on PR #16 (slice 3's decision 13) is unchanged.

## The early output (task 5)

Dev VM, `claude-haiku-5-5`, window 20000 (trigger 16000), session `bb28a18d…`, one turn: "Turn 1: run `seq 1
3000` exactly as written, without pipes, filters or redirection, then read its whole output and tell me only the
last line it printed." `seq`'s output was truncated at 16384 bytes, and the model read it again with
`get_process_status`, so the window filled twice:

| Compaction | Trigger | Estimated tokens | Messages cut | Summary request (in / out) | Next input tokens |
|---|---|---|---|---|---|
| 1 | threshold | 22176 | 5 | 3602 / 577 | 4966 |
| 2 | threshold | 21532 | 5 | 4187 / 1229 | 5065 |

The run: 8 requests, 5 tool calls, 62049 input tokens, answer "The last line printed was **3000**", with the
truncation stated. Screenshots: [`evidence/slice-2/live/`](../evidence/slice-2/live/) (`01-*-compaction.png`,
`02-*-compaction-open.png`, light and dark, taken from the saved session); the archived chat with both summaries
verbatim: `evidence/slice-2/live/16-turn-1-run-seq-1-3000-exactly-as-written-without-p.md`. The second summary
corrects the first ("superseded by the offset-2 result") and carries the user's no-pipes constraint forward.

## Rulings (decision — why — cost if wrong)

- **Fake agent window 6000, not 8000**: FunctionModel's usage omits tool schemas. — An early compaction in a long
  fake session.
- **`check_compaction` matches `… the command ran\. Its output was:`, constant `COMPACTION_XSS`**: turn numbers
  restart after a compaction; `XSS` exists. — None; plan rewritten.
- **`compaction_live` wants ≥ 1 divider**: the live turn compacted twice. — None.
- **Screenshots from the saved session, not a second live run**: the approval covered one more run. — Screenshots
  of a reload rather than the live moment (the local Playwright runs cover live).
- **The fake agent's second `compact` in a compacted session answers without compacting**: documented, not
  changed; no check hits it. — A misleading answer in a hand-run fake session.
