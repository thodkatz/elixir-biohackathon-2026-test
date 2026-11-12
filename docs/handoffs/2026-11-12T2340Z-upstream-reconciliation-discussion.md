# 2026-11-12: upstream reconciliation discussion

**Attended session, no unit claimed.** The user and the agent re-checked the fork against upstream and reframed the
fork's role. Everything is on `main` and pushed; `biohackathon`'s pin follows up to `b720ace` (move it to the
latest commit when you next push).

## What was done

- `7a2a348`: *Overrides* in `AGENTS.md`: a mechanical rename (no behaviour change, tests passing) is a direct commit.
- `docs/investigations/2026-11-12-upstream-reconciliation.md` (`8d7ce92`, `b720ace`, `0286504`): read it first. It
  holds the checked comparison (upstream unchanged at `847842f`; the 11 merge conflicts; Yasin's `leak-controls`,
  Josef's threatlab), the frame the user settled on (**red** finds attacks: threatlab; **blue** proposes
  mitigations: a person; **judge**: the fork's harness, with its acceptance rule), the baseline as the previous
  commit, a mitigation's granularity (one control at one enforcement point, shown by a model-free probe), and the
  *Reconciliation plan*.
- `BACKLOG.md` *Next*: a new *Reconcile with upstream* item; the level-free experiments item became *Close the loop*.

## Next

The user is mid-discussion; **ask before starting a unit.** The next unit, when they agree, is the plan's step 1:
merge `upstream/main` into `main` (change PR, merged with a merge commit), before `leak-controls` lands. Open
questions for the user, from the investigation's last paragraph: the study-id exemption, the stance on guards that
know the canaries, who raises step 2 upstream, and whether Kraatz sees threatlab as upstream's direction. Offered
and not yet answered: adding the two-chat attack (one chat poisons TRS, the next triggers it) to the backlog as an
input for *Close the loop*.
