# Working with agents — {{project}}

Journal, cards, branches, docs — only via `{{cli}}` (help: `{{cli}} <command> -h`, `.dpcli/README.md`). Agents exchange IDs and commands, never retell the journal (report, review, status); details live in the journal.

**Language.** Everything written for people — replies to the user, reports, journal entries, plans, docs — in {{language_text}}. Commit messages in {{language_commits}}.

## Roles
- **User** — decisions, forks, acceptance of the result.
- **Main session** — plans, questions to the user as one list; a module: `{{cli}} module new <m> --area <subproject>` + one `dp-coordinator` (area — from the `areas` config key; if the developer did not name it, ask, don't guess); a module of 2–3 tasks — no coordinator, the main session briefs executors itself. User decisions — `{{cli}} decide <m> "…" --by user --why "…" --plan` (`--why` is the reason; no reason — leave it empty, `decisions.md` will say "approved by the developer"), gate answers — `{{cli}} answer <Qn> "…"`, plan edits — `{{cli}} plan edit … --commit`. Branches: `{{cli}} sync <m>` (fresh module base into the module branch), delivery — `{{cli}} deliver <m>` (only after the user approves), other branches — `{{cli}} merge <branch> --into <target>`, `{{cli}} gc`. Push and releases — only on the user's command.
- **Module coordinator** (`dp-coordinator`) — contracts, task cards, launching executors, acceptance, gates. Does not write or review code.
- **Executor** (`dpcli_role: executor`) — one task in its own copy and branch, within the card's bounds.
- **Reviewer** (`dp-reviewer`) — fresh, empty context, one task; only reads and re-runs checks.

## Lifecycle
1. Plan `{{plan_dir}}/<m>.md`: goal, user decisions, tasks with scope and acceptance, waves, stop conditions.
2. Branch `{{module_branch}}` **from the module base** — the feature branch the main session is on (`module new` takes the current branch; another — `--from`); copy, coordinator; contracts before the first executor. Several modules of one feature — each its own branch from the same feature branch.
3. Waves: ≤ 4 executors at once; task → card → copy and branch `<m>/<ID>` from `{{module_branch}}` → acceptance (see "Acceptance").
4. Gate (stop condition or a fork outside the plan): `{{cli}} decide <m> "question" --ask` → main session asks the user → `answer`.
5. User check → on approval `{{cli}} deliver <m>`: one squash commit into the module base (`--into` — another branch); of the journal only `decisions.md` and `summary.md` go there; the full journal stays in `{{module_branch}}` (and under an archive tag if `deliver.archive_tag` is set); plan and contracts get `status: closed`, `INDEX.md` is rebuilt. Don't develop the module branch after delivery. Feature branch into `{{main_branch}}` — only by the user's decision (usually an MR merged by a human); `deliver`/`merge` into `{{main_branch}}` — only with explicit `--into`.

## Message protocol
Agents send only these formats.

| From → to | Message |
|---|---|
| main → coordinator | `Module <m>: copy <path>, branch <branch>. Plan: {{cli}} plan <m>. New: {{cli}} inbox <m>.` |
| coordinator → executor | output of `{{cli}} task brief <ID>` as is |
| coordinator → reviewer | output of `{{cli}} task brief <ID> --review` as is |
| executor → coordinator | one line: `<ID> reported` \| `<ID> blocked: <reason ≤15 words>` \| `<ID> contract: <what to change>` |
| reviewer → coordinator | `<ID> review accept` \| `<ID> review rework <n issues>` |
| coordinator → main | `<m>: <n> accepted, <n> in progress; gate Q<n>`, `<m>: wave <n> done` (main starts a fresh coordinator for the next wave) or `<m> done` |
| main → user | free form, from `{{cli}} status` / `{{cli}} digest` |

- User decisions are already in the inbox (via `decide`); don't retell them in messages.
- Add nothing to `brief`: task specifics go into the card (`{{cli}} task note <ID> "…"`).
- Missing information — ask in one line. New rules for a running agent — by message, no restart.

## Task card — boundaries
The coordinator writes it so the executor has nothing to search for:
- `goal` — 1–2 sentences, what must come out;
- `scope` — files/dirs that change; `dont_touch` — where there is temptation or risk; paths or globs only, exceptions as `!path`;
- `accept` checks: `--test <filter>` or `--check <name> "<cmd>" "<expect>"` — executable, with thresholds;
- interface contracts with versions (`--contract <name>@<version>`);
- how to do it when not obvious — `task note` (files, functions, format, GPU/CPU lock, where data is).

`task brief` refuses an incomplete card; `accept` checks that changed files are within `scope`.

## Contracts
`{{contracts_dir}}/<m>.md` — per interface: owner and consumers, the exact interface (signatures, fields, units, axes, types, behaviour on missing data, invariants), version.
- Record what exists in code; report discrepancies.
- Only the coordinator changes an interface: version +1, notify consumers, their fix in the same step.
- A contract test breaks if the format changed without updating the contract.
- Bulk data between tasks — format in the contract with a version; compact, with a schema, written once (temp file + rename).

## Acceptance
The coordinator does not read the task's code, diffs or logs. Allowed: `status`, `log`, `report --show`, `review --show`, the `accept` result, `git diff --stat` when merging.
1. `{{cli}} accept <ID>`. FAIL → rework (same executor with the result, or a new one with a refined card).
2. PASS, `dpcli_review: false` → `accepted`.
3. PASS, `dpcli_review: true` → `checked`, then by risk:
   - by default — by the report (`report --show`: checks, `uncertain`) → `{{cli}} event <ID> accepted --note "by report"`;
   - a fresh `dp-reviewer` — complex domain logic, numerical schemes, parallel/GPU computing, a contract interface, second rework, serious `uncertain`.
4. Reviewer verdict: accept → `event accepted --note "by review"`; rework → to the executor: `{{cli}} review <ID> --show`, then `accept` again and a fresh reviewer. Disputed points — a question to the reviewer/executor.
5. Merge the task branch into `{{module_branch}}`, `{{cli}} accept <ID> --here --commit <h>`, `{{cli}} event <ID> merged`, remove the copy.

## General rules
- Refer to decisions in plans, contracts and cards by `Q<n>` or date `YYYY-MM-DD`, not by time ("decision 12:35"): after delivery the journal with timestamps is not in the branch.
- Deterministic work — `{{cli}}` commands (`search`, `plan`, `docs`, `log`, `status`, `task`, `sync/merge`); don't write your own grep/scripts over the journal, plans and docs. A command is missing — work around once and log feedback.
- Correctness over "looks nice": parameters are justified (domain, measurements, sources), numbers come from measurements, results from reports; assumptions and limits go into the report.
- Minor visual/style details — at most 2 attempts.
- Tools: files — Read (offset/limit), Edit, Write; not `sed -n`/`sed -i`/`cat >`/`python3 -` replacements. Bash runs programs: search — `rg`, files — `fd`, JSON — `jq`, structural search/rewrite of code — `ast-grep`; Python beyond one line — a script file (`uv run` / `python3 file.py`).
- Tests — non-interactive. GPU — `{{cli}} lock gpu <name> -- <cmd>`, heavy CPU — `{{cli}} lock cpu …`.
- Long runs (> 1–2 min) — `run_in_background` or `{{cli}} job start <name> <timeout> <cmd>` → `{{cli}} job wait <name>`. No `pgrep -f`/`pkill -f`; other processes — only by PID after `readlink /proc/PID/cwd`.
- Batches of runs — one script, one background run, results as a table.
- Don't open images unless appearance is the subject of the task; verify with numbers. Artifacts — in `artifacts_dir`, a subfolder per task.
- Read plans and contracts by section: `{{cli}} plan <m> <section>`, `--contracts <name>`.
- Commits — only your own files: `git add <paths> && git commit -m "…" -- <paths>`, with a `Claude-Session` line; no push. Never `git stash`: the stash is shared by all worktrees.
- Don't change `.claude/` or CLAUDE.md unless that is the task.

## Journal
- `{{plan_dir}}/<m>/` — cards, reports, `events.jsonl`, `decisions.jsonl`; append-only via commands, never edit by hand. It is the module branch's working journal: commit it there freely, it does not go into the target branch — `deliver` folds it into `decisions.md` (decisions, questions with answers) and `summary.md` (task results, not done, doubts). Full view for the coordinator — `{{cli}} render <m>`.
- Task ID `<CODE>-<n>[letter]`; `task new <m>` without an ID takes the next number.
- Executor: `{{cli}} task show <ID>` → work → `{{cli}} accept <ID> --dry` → `{{cli}} report <ID>` (per-task file; schema `report --template`; `uncertain` — doubts and what was checked; `dp_feedback`). `report` is the only write into the module copy.
- Coordinator: `{{cli}} inbox <m>` at the start of every step; journal commit — `git add {{plan_dir}}/<m> && git commit -m "…" -- {{plan_dir}}/<m>`.

## Documentation
- Entry — `{{docs_dir}}/INDEX.md`. Find — `{{cli}} docs find <words>`, `{{cli}} docs findings <words>`, module journals — `{{cli}} search <text>` (`--sem` — by meaning, if enabled).
- Read by section, not whole: `{{cli}} docs section <path>` — table of contents, `{{cli}} docs section <path> <number|heading start>` — a section.
- Every md has frontmatter (`type`, `status`, `module`, `updated`, `summary`, `related`); new — `{{cli}} docs init`; `summary` — the conclusion/purpose in one line ≤ 140 chars (not TODO).
- Document size ≤ `docs.max_kb` (40 KB): larger — split into section files or move data out; before commit — `{{cli}} docs check`, registries — `{{cli}} docs index`.
- Finished work — one line in `registry/findings.md` (module section): the conclusion with numbers and a `path#section` link.

## Agents and models
| Type | Model | For |
|---|---|---|
| `dp-coordinator` | sonnet | module coordinator |
| `dp-engineer` | sonnet | code and tests |
| `dp-researcher` | sonnet | prototypes, measurements, literature |
| `dp-writer` | sonnet | documents |
| `dp-mechanic` | haiku | pattern replacements, runs, conflict-free merges |
| `dp-reviewer` | sonnet | risk-based review; hardest tasks — launch with `model: opus` |
| `dp-status` | haiku | status summary for the main session |

Opus only if the design cannot be moved into the plan or a contract. On failure — refine the card first, the model second.

## Agent setup
- dpcli agents — `.dpcli/agents/*.md` (Claude Code format + `dpcli_role: coordinator|executor|reviewer|status`, `dpcli_review: true|false`); `{{cli}} init` puts them into `.claude/agents/`.
- Project changes live in the project layer `.dpcli-local/` (see its README), never in `.dpcli/` — the distribution is replaced on update: `agents/<name>.append.md` adds to a dpcli agent, `agents/<name>.md` is an own agent, `skills/<name>/`, `workflow.md` (project rules), `claude-md.md`. Then `{{cli}} init`.
- `init` does not touch files it did not create: same-named files in `.claude/agents/` are skipped.
- Attach your own agent to a role — `roles` in `dpcli.yml` (`name: {role: executor, review: true}`) or `dpcli_role` in its frontmatter; then it is valid in `task new --type`.
- Role registry — `{{cli}} agents`.

## Monitoring
- The main session does not poll: it wakes on a coordinator message or the user's request — then `{{cli}} status --since <period>` (stalls — `dp-status`); daily summary — `{{cli}} digest --since today`.
- Stall: "⚠quiet" > 30–40 min — find out what it is doing, report.

## Sessions and context
Every turn pays for the whole session context again.
- One session — one phase or module. After a merge, module acceptance or a change of topic — `/clear` or a new session; state is restored from the journal (`{{cli}} status`, `inbox`), not from session memory.
- With a long context the main session does not read or edit code itself: a task for an executor or a fresh session.
- Subagents — only when needed (protocol, waves).

## Self-improvement
The process (agents, templates, rules, permissions, dpcli) improves as you work, but changes only with the user's approval.
- **Collect — everyone, as you go, one line.** Friction = an extra rework round, waiting for a permission, working around a dpcli command, a rule that hinders or contradicts, wasted tokens/time, a repeated mistake. Executor — the report's `dp_feedback`; reviewer — the review's `harness`; coordinator and main session — `{{cli}} event <m> note --note "harness: <what hurt> → <what to change>"`.
- **Review — main session, skill `harness-retro`:** on `<m> done`, once per phase or on the user's request: `{{cli}} feedback` (clusters, triage project|dpcli), `{{cli}} stats`, ≤ 3 proposals to the user.
- **Where fixes go.** Project-specific — `.dpcli-local/` (survives updates). dpcli itself — edits in `.dpcli` leave only via `{{cli}} contribute F-n` (branch, commit, a PR to the dpcli hub or a +1 on a similar one); everyone gets it with the next update.
- The user's remarks about the work — into memory (feedback) at once, without waiting for a review.
