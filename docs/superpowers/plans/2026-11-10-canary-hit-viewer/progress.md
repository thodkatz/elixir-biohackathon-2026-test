# Canary hit viewer — progress and rulings

Rulings slices made where they departed from or filled in the plan: *decision, why, cost if wrong*. Status per
slice is the README's slices table; the handoffs say what each session did.

## Slice 1

1. **Archive hits keep their underlying source; Open WebUI export hits are `archive`.** A run's journal and run
   log hits keep `agui-journal` and `agent-runs`, so a hit found live and found again in the archive has one dedup
   key; `openwebui-export.json` has no live twin in slice 1, so its hits are `archive`. *Cost if wrong:* a
   `source` filter on the admin page groups archive hits under the live source; relabel in slice 4.
2. **The early output on the portal is root-only** (`/data-share/canary-hits/early-output/`, root:root, dir 0750,
   files 0640) instead of plan ruling 4's group read: the portal has no `sperange-report` group (`getent` empty,
   2026-11-10). The user reads it with `sudo`. Slice 2's hits root setup re-owns `/data-share/canary-hits`.
   *Cost if wrong:* none.
3. **Receiver hits share one dedup key per canary per generation** (the spec's key, *Sources*): one `delivered`
   hit per canary, not one per request. *Cost if wrong:* repeat deliveries are not listed; slice 3 revisits it if
   the page should show each request (carried into slice 2's Task 7).
4. **`_required` lives once, in `canary_record.py`**, and `handoff.py` imports it (the plan's import list
   duplicated it). *Cost if wrong:* none.
5. **`hits.css` duplicates `report.css`'s tokens** so the static page is self-contained (no external stylesheet).
   *Cost if wrong:* the two drift; slice 3's served page links `report.css` and can drop the copy.
6. **Accepted limits** (review of #77): `test_watcher_agrees_with_metrics` reaches `canary_hits` through
   `metrics`' own `sys.path` insert (correct, and one line to make explicit when next touched); the agent run log's
   `answer` joins a run's messages with no separator, so a token right after another message's last word fails
   the whole-word match there, while the journal, one answer per message, still finds it. *Cost if wrong:* a
   run with a run log and no journal misses that one hit.

## Slice 2

1. **Open WebUI's `chat` columns are unverified**: `denbi-agui-01` runs the AG-UI frontend only (no
   `spe-frontend_open-webui-data` volume), so the check moved into slice 3's Task 9. *Cost if wrong:* the reader
   reports `openwebui: <exception>` until a column rename is fixed.
2. **The on-stop scan runs `scan_archive` over the whole run directory** with the workspace's `seen` set and
   generation, not from the offsets reached: the dedup keys (no `source` in them) drop what polling found. *Cost if
   wrong:* one extra read of a run's archive.
3. **`SshTransport` puts its `-o` options before `vm_argv`'s target**, and runs `sudo python3 -` locally when
   `vm_argv` is `[]`. *Cost if wrong:* none.
4. **The watcher caps a reader reply at 32 MiB** (a file with no newline would otherwise be shipped whole); past
   it the poll fails (`unreachable`). Only the participant's own workspace can be stalled this way. *Cost if
   wrong:* such a workspace is watched only by its on-stop archive scan.
5. **A `RecordError` message is logged with the workspace id**: the constraint allows errors, and every
   `RecordError` names a file, key or line, never a value. *Cost if wrong:* a future message carrying a value leaks
   into the log.
6. **The reader returns `line_starts`** (each line's byte offset; Task 5's interface rewritten): restart needs the
   exact offset of an open run's `run_start`, and lines are decoded with `errors="replace"`. *Cost if wrong:* none.
7. **Beyond the plan**: journal titles are kept in the state file (a restart keeps them); a journal file whose name
   is not a UUID is skipped, not a failed poll; the state records `generation_start` (hits-file line count at the
   generation's start) so a restart rebuilds dedup keys from this generation's hits only (review fix). *Cost if
   wrong:* none.
