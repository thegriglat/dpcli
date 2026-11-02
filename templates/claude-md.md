## Working with agents (dpcli)

Before multi-step work read **`{{workflow}}`**. Journal, tasks, branches, docs — only via `{{cli}}` (`{{cli}} -h`), one command per Bash call: chained with `&&` / `cd …;` it misses the `Bash({{cli}} *)` permission and may be refused.

- Language: replies, reports, journal, plans, docs — {{language_text}}; commit messages — {{language_commits}}.
- Roles: user — decisions; main session — plans, module coordinators, reports on events (gate, `<m> done`) or on request, merges into `{{main_branch}}` on approval; `dp-coordinator` — contracts, cards, acceptance, gates; executor — one task in its own copy.
- Messages follow the protocol ({{workflow}}, "Message protocol"): IDs and commands, no retelling of the journal.
- Deterministic work — `{{cli}}` commands; the journal `{{plan_dir}}/<m>/` is append-only.
- Correctness over "looks nice"; don't invent; don't polish.
- One session — one phase/module: after a merge or a change of topic — `/clear`, state comes from the journal.
- Process frictions — at once, one line `harness: …` (in `dp_feedback` or `event <m> note`); review and process changes — skill `harness-retro`, only with the user's approval.
- Docs — entry `{{docs_dir}}/INDEX.md`; find with `{{cli}} docs find`, read by section `{{cli}} docs section <path> [section]`, not whole.
- Commits — only your own files (`git commit -- <paths>`); no push without the user's command; after a merge `{{cli}} gc --remove`.
- Agents — `.dpcli/agents/`, process — `.dpcli/templates/workflow.md`; `.claude/` is refreshed by `{{cli}} init`.
