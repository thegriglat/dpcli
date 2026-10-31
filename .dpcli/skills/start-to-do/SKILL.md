---
name: start-to-do
description: Start a task (plan item) by the {{project}} module coordinator — check contracts, create the card (copy and branch are created automatically), hand the executor the `task brief`, record it in the journal. For the coordinator (dp-coordinator) before launching each executor.
---

# start-to-do — start a task

Argument: a task from the module plan (`<ID>` or section).

1. **Contracts.** `{{cli}} plan <m> <section>` — scope, files, acceptance, dependencies. Seams — `{{cli}} plan <m> --contracts <name>`: no contract for a new seam — describe it first (version, contract test). Dependency not ready and no stub data — don't start.
2. **Card** (creates copy and branch `<m>/<ID>` from `{{module_branch}}`):
   ```
   {{cli}} task new <m> [ID] --type <type> --title "…" --goal "1–2 sentences" --plan-ref "<section>" \
     --scope <path> --dont-touch <path> --contract <name>@<version> \
     --test <filter> --check <name> "<cmd>" "<exit=0|re:…|num:(…) <=X>"
   ```
   How to do it, if not obvious (files, functions, format, GPU/CPU lock, where data is), — `{{cli}} task note <ID> "…"`. The executor should not need to look anything up.
3. **Brief.** `{{cli}} task brief <ID>` — a refusal means the card is incomplete: fill it in (`task set`/`task note`).
4. **Launch.** Agent of the card type (`--type`), message — `brief` output as is, nothing added. Model — sonnet (`dp-mechanic` — haiku); opus — only if design can't be moved into the card/contract.
5. **Journal.** `{{cli}} event <ID> started`.

| Work | Type |
|---|---|
| code and tests | `dp-engineer` |
| prototype, measurements, literature | `dp-researcher` |
| documents | `dp-writer` |
| pattern replacements, runs | `dp-mechanic` |

Custom types — `{{cli}} agents`. Acceptance — {{workflow}}, "Acceptance".
