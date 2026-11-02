# `node --test lib/` fails on Node 24: pass a glob

**Symptom.** In `platform/agui/copilotkit-chat`, `node --test lib/` (Node 24.21.0) runs no test file. It
treats `lib` as one module to load and reports a single failed "test":

```
Error: Cannot find module '/…/platform/agui/copilotkit-chat/lib'
  code: 'MODULE_NOT_FOUND',
✖ lib (34.217076ms)
ℹ tests 1
```

It exits 1.

**Fix.** Give `node --test` a quoted glob, which Node expands itself (the shell must not):

```bash
node --test 'lib/*.test.ts'
```

That is what `npm test` runs (`package.json`), with Node's type stripping for the `.ts` files. Expect
`ℹ tests 43` / `ℹ fail 0` as of the session store's first version; a count of 1 means the glob was not
expanded.
