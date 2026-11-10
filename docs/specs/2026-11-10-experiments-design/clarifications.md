# Clarifications

Numbered, append-only: why the design changed after approval.

1. **A contribution has a kind: red, blue, end-to-end or other** (2026-11-10; spec PR, the user in session). A
   red PR adds an attack and shows its harm on a named base (`mitigation: null`); a blue PR adds a mitigation
   measured against attacks already on `main`; end-to-end is the former single kind; other is not an experiment.
   A new threat or path comes only with an attack. `check_experiment.py` reads the kind from the files against
   `--base`; a PR template per kind, opened through `spe-eval pr-body`'s link since GitHub has no PR template
   picker; labels added by the reviewer until CI exists. The end-to-end template gains the *Attack* line and *Idea
   and rationale* (from `BACKLOG.md`). *Reason:* participants come as red or blue teams and should contribute one
   side without building the whole chain, while every merged piece stays measured. *Amends:* decisions 17 and 18,
   05 (*Kinds of contribution*, the path, the checker, the PR, the guides), 07 (*Commands*), slice 6, the glossary,
   approaches, out of scope. *Status:* folded.
