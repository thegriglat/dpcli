# Agent workflow — {{project}}

Journal, cards, branches, docs — only via `{{cli}}` (help `{{cli}} <command> -h`, `.dpcli/README.md`). The goal is context economy: agents exchange IDs and commands, details live in the journal.

## Roles
- **User** — decisions, forks, acceptance of the result.
- **Main session** — plans, questions to the user in a single list; module: `{{cli}} module new <m> --area <subproject>` + one `dp-coordinator` (area — from the `areas` config key; developer didn't name it — ask explicitly, don't guess); a module of 2–3 tasks — no coordinator, main gives tasks to executors itself. User decisions — `{{cli}} decide <m> "…" --by user --why "…" --plan` (`--why` — the reason; no reason — don't write "user answer", leave it empty: `decisions.md` will say "approved by developer"), gate answers — `{{cli}} answer <Qn> "…"`, plan edits — `{{cli}} plan edit … --commit`. Branches: `{{cli}} sync <m>` (fresh changes from module base into module branch), module delivery — `{{cli}} deliver <m>` (only after user approval), other branches — `{{cli}} merge <branch> --into <target>`, `{{cli}} gc`. Push and versions — only on user command.
- **Module coordinator** (`dp-coordinator`) — contracts, task cards, launching executors, acceptance, gates. Doesn't write or review code.
- **Executor** (`dpcli_role: executor`) — one task in its own copy and branch, within the card's boundaries.
- **Reviewer** (`dp-reviewer`) — fresh, empty context, one task; only reads and reruns checks.

## Lifecycle
1. Plan `{{plan_dir}}/<m>.md`: goal, user decisions, tasks with scope and acceptance, waves, stop conditions.
2. Branch `{{module_branch}}` **from the module base** — the task's feature branch the main session is on (`module new` takes the current branch; another — `--from`); copy, coordinator; contracts — before the first executor. Several modules of one task — each its own branch from the same feature branch.
3. Waves: ≤ 4 executors at once; task → card → copy and branch `<m>/<ID>` from `{{module_branch}}` → acceptance → merge into `{{module_branch}}` → `{{cli}} accept <ID> --here` → remove copy.
4. Gate (stop condition or fork outside the plan): `{{cli}} decide <m> "question" --ask` → main asks the user → `answer`.
5. User check → on approval `{{cli}} deliver <m>`: one squash commit into the module base (feature branch; `--into` — another branch), only `decisions.md` and `summary.md` from the journal go there; full journal stays in `{{module_branch}}` (and under an archive tag if `deliver.archive_tag` is set); module plan and contracts get `status: closed`, `INDEX.md` is rebuilt. Don't develop the module branch after delivery. Feature branch into `{{main_branch}}` — only by user decision (usually an MR merged by a human); `deliver`/`merge` into `{{main_branch}}` — only with explicit `--into`.

## Message protocol
Agents send only these formats. Details are in the journal, read them with commands.

| From → to | Message |
|---|---|
| main → coordinator | `Module <m>: copy <path>, branch <branch>. Plan: {{cli}} plan <m>. New: {{cli}} inbox <m>.` |
| coordinator → executor | output of `{{cli}} task brief <ID>` as is |
| coordinator → reviewer | output of `{{cli}} task brief <ID> --review` as is |
| executor → coordinator | one line: `<ID> reported` \| `<ID> blocked: <reason ≤15 words>` \| `<ID> contract: <what to change>` |
| reviewer → coordinator | `<ID> review accept` \| `<ID> review rework <n issues>` |
| coordinator → main | `<m>: <n> accepted, <n> in progress; gate Q<n>` or `<m> done` |
| main → user | free form, from `{{cli}} status` / `{{cli}} digest` |

- User decisions are already in inbox (via `decide`); don't retell them in messages.
- Add nothing to `brief`: task specifics go into the card (`{{cli}} task note <ID> "…"`).
- Don't retell what's in the journal (report, review, status) — give the ID.
- Missing information — ask in one line, don't read someone else's context.
- New rules for a running agent — by message, no restart.

## Task card — boundaries
Executor quality is determined by card clarity. The coordinator writes it so the executor needn't look anything up:
- `goal` — 1–2 sentences on what should result;
- `scope` — files/directories that change; `dont_touch` — where there's temptation or risk;
- `accept` checks: `--test <filter>` or `--check <name> "<cmd>" "<expect>"` — executable, with thresholds;
- seam contracts with versions (`--contract <name>@<version>`);
- how to do it, if not obvious, — `task note` (files, functions, format, GPU/CPU lock, where data is).

`task brief` refuses an incomplete card; `accept` checks that changed files are within `scope`.

## Contracts
`{{contracts_dir}}/<m>.md` — per seam: owner and consumers, exact interface (signatures, fields, units, axes, types, behavior on missing data, invariants), version.
- Record what is already in the code; find and hand out discrepancies.
- Interface changes — coordinator only: version +1, notify consumers, their fix in the same step.
- A contract test breaks if the format changed without a contract update.
- Bulk data between tasks — format in the contract with a version; compact with a schema, written once (temp file + rename).

## Acceptance
The coordinator doesn't read task code, diffs or logs. Allowed: `status`, `log`, `report --show`, `review --show`, `accept` result, `git diff --stat` on merge.
1. `{{cli}} accept <ID>`. FAIL → rework (same executor with the result, or a new one with a refined card).
2. PASS, `dpcli_review: false` → `accepted`.
3. PASS, `dpcli_review: true` → `checked`, then by risk:
   - default — by report (`report --show`: checks, `uncertain`) → `{{cli}} event <ID> accepted --note "by report"`;
   - fresh `dp-reviewer` — complex domain logic, numerical schemes, parallel/GPU computation, contract seam, second rework, serious `uncertain`.
4. Reviewer verdict: accept → `event accepted --note "by review"`; rework → to executor: `{{cli}} review <ID> --show`, then `accept` again and a fresh reviewer. Disputes — a question to reviewer/executor.
5. Merge task branch into `{{module_branch}}`, `{{cli}} accept <ID> --here --commit <h>`, `{{cli}} event <ID> merged`, remove copy.

## General rules
- Refer to decisions in plans, contracts and cards by `Q<n>` or date `YYYY-MM-DD`, not by time ("decision 12:35"): after delivery the journal with record times is not in the branch.
- Deterministic work — via `{{cli}}` commands (`search`, `plan`, `docs`, `log`, `status`, `task`, `sync/merge`); don't write your own grep/scripts over journal, plans and docs. Missing command — work around once and record feedback.
- Agents do only what needs thought: design, root-cause, write code/text.
- Correctness over "looks nice": parameters are justified (domain, measurements, sources); assumptions and solution limits — in the report.
- Don't invent: numbers — from measurements, results — from reports.
- Don't polish: minor visual/stylistic details — no more than 2 attempts.
- Tests — non-interactive. GPU — `{{cli}} lock gpu <name> -- <cmd>`, heavy CPU — `{{cli}} lock cpu …`.
- Long runs (> 1–2 min) — `run_in_background` or `{{cli}} job start <name> <timeout> <cmd>` → `{{cli}} job wait <name>`. No `pgrep -f`/`pkill -f`; other processes — only by PID after `readlink /proc/PID/cwd`.
- Batches of runs — one script, one background run, results as a table; not a "run → look" loop.
- Don't open images unless appearance is the subject of the task; verify with numbers. Artifacts — in `artifacts_dir`, task subfolder.
- Read plan and contracts by section: `{{cli}} plan <m> <section>`, `--contracts <name>`.
- Commits — only your own files: `git add <paths> && git commit -m "…" -- <paths>`, with a `Claude-Session` line; don't push.
- `.claude/`, CLAUDE.md — don't change unless that's the task.

## Journal
- `{{plan_dir}}/<m>/` — cards, reports, `events.jsonl`, `decisions.jsonl`; append-only via commands, don't edit by hand. It's the working journal of the module branch: commit it in the module branch however you like, it doesn't go into the target branch — `deliver` folds it into `decisions.md` (decisions, questions with answers) and `summary.md` (task results, not done, doubts). Full view for the coordinator — `{{cli}} render <m>`.
- Task ID `<CODE>-<n>[letter]`; `task new <m>` without ID takes the next number.
- Executor: `{{cli}} task show <ID>` → work → `{{cli}} accept <ID> --dry` → `{{cli}} report <ID> < r.json` (schema `report --template`; `uncertain` — doubts and what was verified; `dp_feedback`). `report` is the only write into the module copy.
- Coordinator: `{{cli}} inbox <m>` at the start of every step; journal commit — `git add {{plan_dir}}/<m> && git commit -m "…" -- {{plan_dir}}/<m>`; at the end — `{{cli}} event <m> note --note "dpcli: …"`.
- Past modules — `{{cli}} search <text>` (`--sem` — semantic, if enabled).

## Documentation
- Entry — `{{docs_dir}}/INDEX.md` (one line per document). Find — `{{cli}} docs find <words>`, `{{cli}} docs findings <words>`, module journals — `{{cli}} search`.
- Read by section, not whole: `{{cli}} docs section <path>` — TOC, `{{cli}} docs section <path> <number|heading prefix>` — section.
- Every md — with frontmatter (`type`, `status`, `module`, `updated`, `summary`, `related`); new — `{{cli}} docs init`; `summary` — conclusion/purpose in one line ≤ 140 chars (not TODO).
- Document size ≤ `docs.max_kb` (40 KB): larger — split into section files or move data out; before commit — `{{cli}} docs check`, registries — `{{cli}} docs index`.
- Finished work — one line in `registry/findings.md` (module section): conclusion with numbers and a `path#section` link.

## Agents and models
| Type | Model | Purpose |
|---|---|---|
| `dp-coordinator` | opus | module coordinator |
| `dp-engineer` | sonnet | code and tests |
| `dp-researcher` | sonnet | prototypes, measurements, literature |
| `dp-writer` | sonnet | documents |
| `dp-mechanic` | haiku | pattern replacements, runs, conflict-free merges |
| `dp-reviewer` | opus | risk-based review |
| `dp-status` | haiku | status summary for main |

Executors — sonnet (mechanic — haiku). Opus — only if the task needs design that can't be moved into the plan or contract. On failure — refine the card first, then change the model.

## Agent setup
- dpcli agents — `.dpcli/agents/*.md` (Claude Code format + `dpcli_role: coordinator|executor|reviewer|status`, `dpcli_review: true|false`); `{{cli}} init` puts them into `.claude/agents/`.
- `init` doesn't touch project agents: same-name files in `.claude/agents/` are skipped.
- Attach your own agent to a role — `roles` key in `dpcli.yml` (`name: {role: executor, review: true}`) or `dpcli_role` in frontmatter; then it's valid in `task new --type`.
- Role registry — `{{cli}} agents`.

## Monitoring
- Every 30 min main runs `{{cli}} status --since 30m` (stall investigation — `dp-status`); end of day — `{{cli}} digest --since today`.
- Stall: task flagged "⚠" (quiet) > 30–40 min — find out what it's doing, report.
