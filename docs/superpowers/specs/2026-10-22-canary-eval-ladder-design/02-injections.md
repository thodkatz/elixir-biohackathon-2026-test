# Injections

*To be written by the team.* README decision 4 fixes the interface the other parts rely on:

- Ansible plants injections through `spe_inject_*` switches, on at every level.
- Payloads are committed files that name a target and an action, never a canary token.
- The build writes `injections.json` to the hand-off directory: one entry per planted injection, with where it
  was planted and what it asks for, so the scoring can tell whether a test followed it
  ([04](04-agent-suite-and-scoring.md), `injection.followed`).

This part must settle: the payload files and their location, the switches and which build scripts take them,
the `injections.json` schema, and the unit tests named in decision 4's acceptance check.
