---
name: start-to-do
description: "Start a task (a plan item) by the {{project}} module coordinator — check contracts, create the card (copy and branch are created automatically), give the executor `task brief`, log it. Used by the coordinator (dp-coordinator) before launching each executor."
---

# start-to-do — starting a task

Argument: a task from the module plan (`<ID>` or a section).

1. **Contracts.** `{{cli}} plan <m> <section>` — scope, files, acceptance, dependencies. Interfaces — `{{cli}} plan <m> --contracts <name>`: no contract for a new interface — describe it first (version, contract test). A dependency is not ready and there is no stub data — don't start.
2. **Card** (creates the copy and branch `<m>/<ID>` from `{{module_branch}}`):
   ```
   {{cli}} task new <m> [ID] --type <type> --title "…" --goal "1–2 sentences" --plan-ref "<section>" \
     --scope <path> --dont-touch <path> --contract <name>@<version> \
     --test <filter> --check <name> "<cmd>" "<exit=0|re:…|num:(…) <=X>"
   ```
   How to do it when not obvious (files, functions, format, GPU/CPU lock, where data is) — `{{cli}} task note <ID> "…"`. The executor must not need to search for anything.
3. **Assignment.** `{{cli}} task brief <ID>` — a refusal means the card is incomplete: fill it in (`task set`/`task note`).
4. **Launch.** An agent of the card's type (`--type`), the message — the `brief` output as is, nothing added. Model — the table in {{workflow}}, "Agents and models".
5. **Journal.** `{{cli}} event <ID> started`.

| Work | Type |
|---|---|
| code and tests | `dp-engineer` |
| prototype, measurements, literature | `dp-researcher` |
| documents | `dp-writer` |
| pattern replacements, runs | `dp-mechanic` |

Custom types — `{{cli}} agents`. Acceptance — {{workflow}}, "Acceptance".
