---
name: harness-retro
description: "Review the {{project}} process (harness) — cluster frictions with `dpcli feedback`, measure with `dpcli stats` and token usage, propose ≤ 3 improvements to the user, apply the approved: project ones in .dpcli-local/, dpcli ones as an issue text for the user. Used by the main session on `<m> done`, once per phase, or when the user asks to improve the process or cut costs."
---

# harness-retro — process review

Cheap: one session, no subagents, only the commands below. Don't read project code.

1. **State.** `{{cli}} feedback` — clusters F-n (open / fixed, `⚠N after fix` = the fix did not work) and unclustered frictions by topic. `{{cli}} stats` — rework rounds, created→accepted, slow checks. `python3 .claude/skills/harness-retro/cost.py --since <YYYY-MM-DD>` — tokens: alarming if the main session's average context > 200k or Opus runs outside the models table.
2. **Cluster.** For a recurring topic (≥ 2) read `{{cli}} feedback show <topic>`, then `{{cli}} feedback new "<anonymized title>" --match "<regex>" --scope project|dpcli --why "<one line>"`. Scope `project` — specific to this codebase or team (fixed in `.dpcli-local/`); `dpcli` — would hurt any project (fixed in dpcli itself). Titles never contain project names, paths or quotes.
3. **Propose to the user** as one list, ≤ 3 items, most frequent/expensive first: `F-n ×count [scope] → change (file) → gain/cost`. Change nothing without approval.
4. **Apply the approved.**
   - project: edit `.dpcli-local/` (`workflow.md`, `claude-md.md`, `agents/<name>.append.md`, `skills/`), `{{cli}} init`, commit `.dpcli-local/ .claude/ CLAUDE.md`, then `{{cli}} feedback fix F-n --where .dpcli-local/<file>`;
   - dpcli: don't edit `.dpcli` (it is replaced on reinstall). Give the user the cluster (`{{cli}} feedback show F-n`) as an anonymized issue text for the dpcli repository; if it hurts now, a temporary workaround in `.dpcli-local/` marked `until: F-n`. After the fixed dpcli is installed — `{{cli}} feedback fix F-n --where "dpcli vN"`.
   - rejected by the user — `{{cli}} feedback wontfix F-n --why "…"`.
5. **Record.** `{{cli}} decide harness "<change>" --by user --why "F-n"` per decision.
