# Runs and results

## `hardening.json`

Written by the build to the hand-off directory, next to `canaries.json`: the level, every hardening switch's
value, the frontend, the agent's model provider and model, and this repo's commit. The restore hook adds the
measured restore time. Every report is labelled from it.

## One ladder run (decision 10)

`platform/promptfoo-evals/run.sh <hand-off dir>`, per level and model:

1. `npm run eval:controls`: the controls suite. Writes `reports/controls.json`.
2. If any probe disagrees with the level, stop with a non-zero exit, before any model call.
3. `npm run eval:agent -- --repeat N --no-cache`: the agent suite. Writes `reports/agent.json`.

`maxConcurrency: 1` stays: all tests share one instance. Running the agent suite makes paid model calls and
needs the user's OK each time (`AGENTS.md`, *Working rules*).

## Repeats and cost

`N` is 5 at L0 and at the last level, 3 in between. With the first catalogue (~11 tests), a ladder is about
11 × (5 + 3 × 4 + 5) ≈ 240 agent runs per model, plus restores. Whether de.NBI runs cost money or only rate is
not known.

Models: `qwen3.8-27b` (de.NBI) first, `claude-haiku-5-5` (Anthropic) second. Results from different providers
are not compared cell by cell; the matrix groups by model.

## The matrix (decision 11)

`platform/promptfoo-evals/matrix.py` reads the reports of every level of one model and writes Markdown:

- one row per test (with its group, threat and path), one column per level;
- each cell: the failure count per metric over the repeats (`answer 2/5, touched 3/5`), and for utility tests
  the pass rate;
- above the columns: the controls suite's result per level (all probes as expected, or which disagreed).

It reads only counts and metric names, never tokens or answers, so its output can be committed and cited in a
`biohackathon` knowledge record. The raw reports and `.promptfoo/` stay git-ignored and are deleted after use.
