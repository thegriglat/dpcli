# Roadmap

Goal: agents follow the process because dpcli enforces it (CLI validation, hooks, rules printed at the point of use), not because a long prompt asks them to; less context per agent.

## Done
- v4–v9 (zolotarev/dpcli): English and language settings, project layer `.dpcli-local/`, friction ledger (`feedback`, `stats`), installer, fast tools.
- v10–v17: fixes from the first project's ledger — 8 of 10 friction clusters closed (155 of 186 reports): truncated addenda, plan sections, shared report files, false scope failures, long accept, lock output, job names, `git stash` rule.
- v18: agents read less — `task show` carries the "General rules" section (≈460 instead of ≈3300 tokens of the process description); a re-review looks only at the previous issues and what changed since; one coordinator per wave.

- v37: journal written only by dpcli (hooks + `report --set`, `event revoke`, `adopt`, hash chain with `⚠ journal` in status/inbox); `scope_guard` at edit time; per-run slots `{slot}`/`{port}` for parallel copies; `accept --baseline`; `SubagentStop` reply-format check.

## Next
Collect frictions with `dpcli feedback`; open directions: hand-edited cards detected after the fact (like the journal chain), baseline results cached per base commit.

Order follows the friction ledgers (`dpcli feedback`). A fix is confirmed when the same friction stops coming back (`⚠ after fix`).
