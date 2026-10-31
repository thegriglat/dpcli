## Agent workflow (dpcli)

Before multi-step work — read **`{{workflow}}`**. Journal, tasks, branches, docs — only via `{{cli}}` (`{{cli}} -h`).

- Roles: user — decisions; main session — plans, module coordinators, report every 30 min, merges into `{{main_branch}}` on approval; `dp-coordinator` — contracts, cards, acceptance, gates; executor — one task in its own copy.
- Messages — per protocol ({{workflow}}, "Message protocol"): IDs and commands, no retelling of the journal.
- Deterministic work — via `{{cli}}` commands; journal `{{plan_dir}}/<m>/` is append-only.
- Correctness over "looks nice"; don't invent; don't polish.
- Docs — entry point `{{docs_dir}}/INDEX.md`; search with `{{cli}} docs find`, read by section `{{cli}} docs section <path> [section]`, not whole.
- Commits — only your own files (`git commit -- <paths>`); don't push without the user's command.
- Agents — `.dpcli/agents/`, workflow — `.dpcli/templates/workflow.md`; `.claude/` is updated by `{{cli}} init`.
