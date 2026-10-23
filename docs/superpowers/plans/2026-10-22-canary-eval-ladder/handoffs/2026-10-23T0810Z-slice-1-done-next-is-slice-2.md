# 2026-10-23T0810Z: slice 1/9 done — scoring offline

PR #3 (`impl/canary-eval-ladder-1-scoring`). Delivered: `handoff.py`, `metrics.py`, `injections_schema.py`,
`matrix.py`, `conftest.py`, tests for each, the catalogue lint; PyYAML in the `dev` group.

- **promptfoo report shape** (task 4, step 5): as assumed. Confirmed against promptfoo 0.124.1 on the scripted
  agent: `testCase` (`assert`, `description`, `metadata`, `options`, `vars`), `gradingResult`
  (`componentResults`, `namedScores`, `pass`, `reason`, `score`, `tokensUsed`; each `componentResults[i]` has
  `assertion`, `pass`, `reason`, `score`), `response` (`cached`, `metadata`, `output`), `failureReason`. A
  top-level `row["error"]` string can be present on an assertion-failure row that is not an error by
  promptfoo's own classification; `matrix._is_error` only looks at `gradingResult` presence, `response.error`
  and `failureReason == 2`, so it is unaffected. No change to `matrix.py` was needed.
- **For slice 2:** `injection.followed` searches each `trs_tools_added` / `wes_runs_added` item's JSON for the
  target path, so it relies on `trs_tools_added[].descriptors` carrying the descriptor text (plan README,
  *State diff*).
- **For slice 3:** `run.sh` copies `hardening.json` next to `controls.json` and `agent.json` in
  `reports/L<n>/`; `matrix.py counts` needs all three. `handoff.check_hardening` is the shape check to
  reuse when writing `hardening.json`.
- **For slice 4:** the handoff role validates `injections.json` with `injections_schema.py`; its `CATALOGUE`
  fixes ids, switches, surfaces, targets and `payload_file` names.
- **For slice 5:** the metrics need `metadata.state_diff` from the provider (a missing one is a configuration
  error), `SPE_HANDOFF_DIR` with a decrypted `canaries.json`, and each test's `metadata.id`.

## Rulings (this slice's departures from the plan)

Decision, why, cost if wrong — full text in `.superpowers/sdd/slice-1-scoring/progress.md`.

- **F1** `metrics.py` imports `_result`/`_calls` from `asserts` instead of copying them — avoids duplication a
  review would flag — cost if wrong: couples `metrics.py` to `asserts`'s private helpers.
- **F2** one catalogue value set, `matrix.CATALOGUE`/`matrix.METRICS`, and `test_catalogue.py` imports it rather
  than keeping a second copy — two copies had already disagreed on `threat`'s values — cost: the lint follows
  `matrix.py` if `matrix.py` is ever wrong.
- **F3** dropped the conftest-only payload test in task 3 (slice 4 checks planted payloads instead) — it tested
  no code — cost: one less tripwire until slice 4 lands.
- **F4** task 5 also writes the new interfaces (`read_hosts`, `check_hardening`, `REPO_ROOT`, `CATALOGUE`,
  `METRICS`, `MatrixError`, the counts JSON shape) into the plan README's *Shared interfaces* — the README
  requires it — cost: none.
- **F5** "a target action without exposure passes" stays as the plan wrote it; task 2 adds spec clarification 3
  instead of narrowing the metric — the spec's part 04 would otherwise be narrowed silently — cost: if the spec
  author disagrees, `injection_followed` changes.
- **F6** reworded task 3's README text: the handoff role runs the schema check *from slice 4*, not yet — the
  original text was untrue at this point in the plan — cost: none.
- **F7** `matrix.py`'s CLI examples use `../../docs/results/...`, relative to `platform/promptfoo-evals` (task
  4) — cost: none.
- **F8** task 5 uses the README's test command with `--with jinja2` — cost: none.
- **F9** `check_hardening` checks `level` against the leading count of ladder controls switched on, with a
  dedicated test (task 1) — the README defines `level` that way, and a stale or foreign `hardening.json` must
  fail (Review Focus 2) — cost: a legitimately hand-edited `level` would be refused.
- **F10** added a parametrized test for a shell-variable host counting as foreign (task 2) — cost: none.
- **F11** the fixture's `trs_tools_added` item carries `"descriptors": []`, matching the *State diff* interface
  (task 2) — cost: none.
- **F12** the `level_dir` fixture uses one shared instance name across levels (task 4) — the README says every
  level of one VM shares one hand-off directory — cost: cosmetic (fixture naming only).
- **F13** `matrix.counts` wraps `handoff.ConfigError` in `MatrixError` (task 4) — the contract promises
  `MatrixError`; `MatrixError` stays a plain `Exception`, not a `ConfigError` subclass, re-raised with `from e`
  — cost: a caller catching only `ConfigError` would miss it (by design: the contract names `MatrixError`).
- **Unlabeled** (task 2 review): the plan's whole-word `_redact` leaks a token adjacent to `_`/alphanumerics in
  tool-data reasons; the Global Constraint "no token in a report reason" wins over the plan's code, so
  tool-data parts are redacted by substring instead, with the test helper checking substrings — cost if wrong:
  over-redaction of reasons (harmless, never under-redaction).

## Deferred minors

- `metrics.py`: `\b403\b` anywhere in a result text adds a `"(HTTP 403)"` label, not only when the 403 is the
  call's own HTTP status (task 2) — label wording only, no mis-scoring. Lands at the final whole-branch review.
- `injections_schema.py:166-177`: checks `target_file` twice (once against the `CATALOGUE` target, once against
  `DATA_SHARE` + `canary_file`) — redundant, not incorrect (task 3). Lands at the final whole-branch review.
- `platform/promptfoo-evals/README.md`, the F6 wording: tense is slightly ambiguous about when the handoff role
  runs the schema check (task 3). Lands at the final whole-branch review.
- `matrix.py:131`: `_label`'s `None` short-circuit also lets a *missing* `group` through unlabelled; the
  catalogue lint (this task) now enforces `group`'s presence upstream of the matrix, so this is defence in
  depth rather than a live gap, but `matrix.py` itself is unchanged (task 4). Lands at the final whole-branch
  review.
- `matrix.py:255`: `main()` catches `handoff.ConfigError`, which is dead code since `counts()` already wraps it
  in `MatrixError` (task 4). Lands at the final whole-branch review.

The final whole-branch review is still to come; nothing above should be read as "reviewed and accepted" yet.

**Resume:**

```bash
cd elixir-biohackathon-2026-test && git fetch && git switch main && git pull --ff-only
ls docs/superpowers/plans/2026-10-22-canary-eval-ladder/handoffs | tail -1   # this file, until slice 2 hands off
(cd platform/promptfoo-evals && uv run --group dev pytest -q)                # green before slice 2 starts
```
