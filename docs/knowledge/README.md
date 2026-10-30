# Project knowledge index

<!-- One line per entry: [topic.md](topic.md) — the symptom or question, and the answer in brief. See
     AGENTS.md, "Project knowledge", for what belongs here. -->
- [gh-pr-create-token.md](gh-pr-create-token.md) — `gh pr create`: "Resource not accessible by personal access token (createPullRequest)": the fine-grained token lacked *Pull requests: write* on the fork (granted 2026-10-22). It has no access to upstream kraatz: open upstream PRs from the compare page.
- [node-test-directory.md](node-test-directory.md) — `node --test lib/` on Node 24: "Cannot find module '…/copilotkit-chat/lib'", `ℹ tests 1` and no test file run: pass the quoted glob, `node --test 'lib/*.test.ts'` (what `npm test` runs).
- [playwright-new-page.md](playwright-new-page.md) — Python Playwright: `page.context.new_page()` after `browser.new_page()` raises "Please use browser.new_context()": open the second tab with `page.context.browser.new_context().new_page()` instead.
