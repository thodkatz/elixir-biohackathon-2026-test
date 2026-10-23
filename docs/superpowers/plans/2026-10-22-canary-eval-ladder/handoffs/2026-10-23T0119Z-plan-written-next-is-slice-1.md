# 2026-10-23T0119Z: plan written, next is slice 1

**State.** The plan is merged with PR #2 (`plan/canary-eval-ladder`): `README.md` (index, shared interfaces,
claims table, slices) and nine slice files. Nothing is implemented. The spec is unchanged by this PR; the spec
clarifications the plan foresees are added by the slices that verify them (README, *Proposed spec
clarifications*; slice 2, task 1; slice 3, task 1).

**Next unit: slice 1/9**, `impl/canary-eval-ladder-1-scoring`. Offline only: no instance, no model calls.
Read the plan's `README.md`, then `slice-1-scoring.md`; follow `superpowers:subagent-driven-development`.

**Decisions taken while planning** (each already lives in the README or the named slice's task text):

- **promptfoo caches Python provider results** (read in promptfoo 0.124.1): both suites run with `--no-cache`.
  Lives in the README's claims table and slice 3, task 1 (which adds the spec clarification).
- **The state diff is taken by the agent provider**, because promptfoo runs assertions before `afterEach`;
  the `beforeEach` hook writes the baseline to `SPE_EVAL_BASELINE`. README, *State diff*; slice 2, task 1
  (clarification); slice 5, task 1 (provider).
- **The state diff carries each new tool's descriptor text** (`descriptors`), so `injection.followed` connects a
  tool registered by any means to its target. README, *State diff*; slice 2, task 3; slice 1, task 2.
- **One hand-off directory for every level**: the de.NBI VM's preflight accepts only `denbi-agui-01`, so
  `L<n>.example.yml` files are overlays without an instance name, and reports are kept per level in
  `reports/L<level>/`. README, npm scripts paragraph; slices 3 (`run.sh`), 4 (`L0.example.yml`), 5–8.
- **Committed per-level counts** (`docs/results/<model>/L<n>.json`), since raw reports are deleted after each
  level. README, `matrix.py` row; slice 1, task 4.
- **L4's switch value is `typed`**, the value `spe_agent_tool_surface` already has, not the spec's
  `ga4gh_typed`. Slice 3, task 1 (clarification).
- **The sandbox runbook is identical at every level**: L1–L3 are infrastructure controls applied without
  touching the agent (spec part 01, *Order*); a varying runbook would confound the matrix. Slices 6–8.
- **L1 adds a small WES write guard**: WESkit cannot refuse workflow attachments, and an attached
  `nextflow.config` runs code even for a TRS workflow. Slice 6, task 3.
- **Decision 3's literal check** (a fresh cloud instance from `example.yml`) needs the user's OK; slice 4
  checks the defaults and the L0 controls run, and slice 6 adds golden renders of today's templates.
- **Slices over the size target**: slice 1 (~1,550 lines, half tests) is kept whole; the others are near it.
- **L4/L5 instance files and runs** wait for the L4 spec: slice 9, task 3 moves them into `BACKLOG.md`.

**Resume:**

```bash
cd elixir-biohackathon-2026-test && git fetch && git switch main && git pull --ff-only
ls docs/superpowers/plans/2026-10-22-canary-eval-ladder/handoffs | tail -1   # this file, until slice 1 hands off
(cd platform/promptfoo-evals && uv run --group dev pytest -q)                # green before slice 1 starts
```
