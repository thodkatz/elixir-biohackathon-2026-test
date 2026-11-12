# Clarifications

Numbered, append-only: why the design changed after approval.

1. **A contribution has a kind: red, blue, end-to-end or other** (2026-11-10; PR #87, the user in session). A
   red PR adds an attack and shows its harm on a named base (`mitigation: null`); a blue PR adds a mitigation
   measured against attacks already on `main`; end-to-end is the former single kind; other is not an experiment.
   A new threat or path comes only with an attack. `check_experiment.py` reads the kind from the files against
   `--base`; a PR template per kind, opened through `spe-eval pr-body`'s link since GitHub has no PR template
   picker; labels added by the reviewer until CI exists. The end-to-end template gains the *Attack* line and *Idea
   and rationale* (from `BACKLOG.md`). Settled by the agent in PR #87's review round, for the user to overrule there:
   *new* is added or changed against the target ref (the git ref, named apart from the experiment's `base:`); the
   kind is read from every catalogue file the branch makes new, so a lone threat, path, mitigation or injection is
   refused, not *other* (a threat idea with no attack is an issue); a new attack against an unchanged mitigation
   under test is refused (a bypass is red, that mitigation in `base`), and an experiment file alone re-measuring an
   existing mitigation on a new base is blue; an experiment may name any catalogued test; `pr-body` refuses only a
   missing arm or harm, leaving a mitigation's effect to the reviewer; labels are named as the kinds. *Reason:* participants come as red or blue teams and should contribute one
   side without building the whole chain, while every merged piece stays measured. *Amends:* decisions 17 and 18,
   01 (*Tests*, *Experiments*), 05 (*Kinds of contribution*, the path, the checker, the PR, the guides), 07 (*Commands*), slice 6, the glossary,
   approaches, out of scope. *Status:* superseded by 2 (its kinds, refusals, templates and labels; *Idea and rationale* stays).
2. **A skeleton to test the stack with, not contribution rules** (2026-11-11; the user in session: "the main idea
   is to provide an end to end skeleton … to leverage to test a system end to end", for our stack, changed
   directly on `main` at their word, without a spec PR). The design gives one slot per part of an evaluation
   (threat, path, attack, mitigation, tests, experiment), filled as an idea needs and reused from the catalogue
   otherwise, with the ladder as the worked example. Dropped: contribution kinds (red, blue, end-to-end, other)
   as anything a tool reads or enforces, the checker's comparison with a target ref, its refusals by a branch's
   shape (a lone threat or path, a blue branch adding a test, two experiment files), `pr-body`'s refusals by
   result (a red run with no harm, a missing mitigated arm), the PR template per kind, the new-PR link that picks
   one, and the kind labels. Kept: the checker's checks that an experiment runs and fits the catalogue; one PR
   template whose sections are each *if any*; `pr-body` filling it in; red, blue and both as words in the guides
   for common shapes. A threat or path alone is now a PR reviewed by hand. *Reason:* clarification 1 turned the
   skeleton into a rulebook, and policing what a contribution contains is not what a hackathon participant needs;
   people read the result. *Cost if wrong:* a PR that shows nothing reaches review; the reviewer says so, and
   the kinds can come back as a checker report without refusals. Also recorded: runtime conflicts between
   mitigations are undetected (fork issue #91), in out of scope. *Amends:* the README's decision paragraph,
   decisions 17 and 18, the glossary (*Kind* becomes *Slot*), 01 (*Tests*, *Experiments*), 05 (rewritten), 07
   (*Commands*), approaches (*How a contribution's kind is known*), out of scope, slice 6, clarification 1.
   *Status:* folded.
3. **The viewer is two containers, not one** (2026-11-11; PR #92, slice 4 task 3). `evals-view` is a stock
   `nginx:1.29-alpine` (configuration only) that owns the network namespace, publishes
   `127.0.0.1:${SPE_EVALS_PORT}` and joins the `evals` network; `evals-promptfoo` (image `spe-evals-view:local`,
   built from `platform/instance/evals-view/Dockerfile`) runs `promptfoo view` with
   `network_mode: service:evals-view`, so its port is on no network of its own. *Reason:* the proxy is a stock
   nginx image and not our code; `promptfoo view` needs Node, which that image does not have; one shared network
   namespace keeps promptfoo's own port off every network, reachable only through the proxy in front of it. Also
   settled: the allow-list the proxy enforces (04, *Read-only*) is GET/HEAD everywhere plus socket.io's own
   `POST /socket.io/` and its websocket upgrade, checked by `platform/dev/tests/test_evals_view.py` against
   0.125.1's own routes; the proxy forwards the raw request path and allows `/socket.io/` only for exactly that raw
   path, since forwarding nginx's decoded path let an encoded CR/LF smuggle a second request (a write) to promptfoo
   (the PR's final review). *Amends:* 04 (*Read-only*, rewritten), the README's decision 14 (named the wrong compose
   service: `promptfoo view` is `evals-promptfoo`, behind the `evals-view` proxy, not the other way round).
   *Status:* folded.
4. **How an eval hit is told apart** (2026-11-11; PR #93, slice 5). The mark is `forwardedProps.spe_source:
   "eval"`; the agent's run log writes `source: eval` or `source: chat` on every run; a hit's field is `origin`
   (`eval` or `chat`, absent read as chat), since a hit's `source` already names where it was found (journal, run
   log, receiver). The receiver now logs each request's time (`at`, epoch seconds): it had none, so a window could
   not be matched. `spe-eval run` writes an opening window line (`end: null`) when it starts, as well as the closing
   one, since a window written only at the end came after the hits a long run makes; a window never closed lasts
   until the next run's start. An eval receiver hit is deduplicated apart from a chat one. *Reason:* each was what
   the decision needed and the code lacked. *Cost if wrong:* a `spe-eval` killed outright leaves its window open
   until the next run, so a participant's receiver hit in between counts as eval. *Amends:* 03 (*Canary hits*).
   *Status:* folded.
5. **Mitigations named for what they do, not their ladder position** (2026-11-12; PR #96). The ladder's
   mitigations are renamed: `L1` → `trs-read-only`, `L2` → `data-tiers`, `L3` → `egress-allowlist`, `L4` →
   `typed-tools`, `L5` → `answer-airlock` (files `mitigations/<id>.yml`, the experiments' `mitigation` and
   `base`, the test catalogue's `closed_by`); their `name`s are unchanged. Ids are kebab-case only, and
   `validate.py` refuses an `L<n>`/`l<n>` id, which would read as a ladder level. The ladder's order is not
   written into the mitigation files: it stays where it already was, the ladder's switch order in code
   (`controls_asserts.py`'s `LADDER`), and a ladder mitigation is one whose `on` sets one of those switches (the
   gate's skip of the ladder's own mitigations and `create.yml`'s contiguity check read it so; `create.yml`'s copy
   of the switch list is pinned to `LADDER` by a test). Unchanged: the experiments `ladder-l0` … `ladder-l3`
   (their ids; their display names now say the mitigation, e.g. *Ladder L1: TRS read-only*) and the ladder
   *levels* (`hardening.json`'s `level`, `reports/L<n>/`, `instances/L<n>.example.yml`, the matrix's columns,
   `docs/results/`). The committed results keep their old `closed_by` labels as written; `matrix.py` reads an old
   `closed_by: L1`…`L5` in a stored report as the new id (`LEGACY_CLOSED_BY`), so a run made before the rename
   still counts, and the committed matrix renders unchanged. *Reason:* the user, 2026-11-12: `L1`, `L2` "which you
   can't really tell" — an id should say what the mitigation does, on the form, in `closed_by` and in an
   experiment. *Cost if wrong:* a workspace built from the `spe-experiments` template before this change carries
   the old ids in its Mitigations parameter and fails `spe-eval` until rebuilt (the template is fork-only, so no
   participant workspace has them). *Amends:* decisions 2, 5, 6 and 19; 01 (the kinds table, *Mitigations*, the
   catalogue's `closed_by`), 02 (the preset description, the contiguity check), 03 (*An arm is its mitigation
   set*), 05 (the attack shape's `base`), 06 (the mitigations row, *The experiments*), 07 (the worked example,
   `new --from`), inputs for the plan (slice 1), out of scope (the planned mitigations). *Status:* folded.
