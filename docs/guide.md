# dpcli — journal, task cards and acceptance

A process tool for the "main session ↔ module coordinator ↔ executors ↔ reviewer" setup in projects run by Claude Code agents. It keeps a per-module journal (task cards, reports, events, decisions, questions to the user), manages branches and working copies (git worktree), runs acceptance checks and merges branches. Output is short; details via `--full`.

Exit codes: 0 — ok, 1 — error or FAIL, 2 — invalid arguments. An error is one line: `dpcli: …`.

## Requirements

- python3 ≥ 3.10 (standard library only; PyYAML is not required — a built-in parser handles a YAML subset);
- git;
- optional: tmux (windows for `job`/`lock`/`accept --bg`); Ollama with the `bge-m3` model is needed only for semantic search (`search --sem`, `index`) and is off by default.

## Installation

Recommended — the installer, in the root of the project:

```sh
curl -fsSL https://raw.githubusercontent.com/zolotarev/dpcli/main/install.sh | bash
# or, with dpcli already present: bash .dpcli/install.sh
```

| Option | |
|---|---|
| `--lang CODE` | language agents write in for people (asked if omitted; default `en`) |
| `--commit-lang CODE` | language of commit messages (asked if omitted; default `en`) |
| `--tools` | install missing fast tools for agents: `rg`, `fd`, `jq`, `ast-grep` |
| `--yes` | no questions, defaults |
| `DPCLI_REPO=url` | install from another hub (a fork) |

It adds the submodule `.dpcli` at the latest release, writes `language` and `worktree.setup` into the config, runs `init`, and prints the commit command (it never commits). A vendored (copied) `.dpcli` is replaced by the submodule; own agents move to `.dpcli-local/agents/`. Rerunning is safe.

Manual installation:

Recommended as a submodule: dpcli is a separate repository, the project pins its version.

```
git submodule add https://github.com/zolotarev/dpcli.git .dpcli
.dpcli/dpcli init
```

In the project's `dpcli.yml`, initialize the submodule in new working copies (`git worktree add` does not check it out):

```yaml
worktree:
  setup: "git submodule update --init .dpcli"
```

Without a submodule — copy the repository contents (without `tests/`, `.git`) into a `.dpcli` directory at the project root and run `.dpcli/dpcli init`.

`init` creates (all idempotent):

| What | Where |
|---|---|
| Config from the example (if there is no config) | `dpcli.yml` |
| Agents with placeholders filled in | `.claude/agents/*.md` |
| Skills | `.claude/skills/<name>/SKILL.md` |
| Process description | `.claude/dpcli-workflow.md` |
| Block between the markers `<!-- dpcli:begin -->` … `<!-- dpcli:end -->` | `CLAUDE.md` |
| Permission `Bash(.dpcli/dpcli *)` | `.claude/settings.json` |
| Lines `.read_*`, `build/dpcli/` | `.gitignore` |

`init` modes:

- re-running is safe: nothing changes if the result is already current; what `init` wrote is tracked in `.claude/.dpcli-manifest.json`; such files edited by hand are not overwritten without `--force` — a message is printed;
- project files (not in the manifest) are never overwritten or deleted by `init`, even with `--force`: if `.claude/agents` already has an agent with a dpcli agent's name, the dpcli agent is skipped ("skipped — project agent; role: see roles in config"); the same goes for a skill with the same name and for the process file. `CLAUDE.md` and `settings.json` get targeted insertions only (the block between markers, one permission);
- `--force` — overwrite/delete hand-edited files that are in the manifest;
- `--check` — only check whether setup is current (writes nothing);
- `--dry-run` — show what would be done;
- `--json` | `--yaml` — config format if one is created (default `dpcli.yml`).

Exact flags: `.dpcli/dpcli init -h`.

After `init`, commit the result (only the main session commits).

## Project layer

`.dpcli-local/` (config key `local_dir`) is committed with the project and rendered by `init` on top of the distribution, so updating `.dpcli` never overwrites project changes:

| Path | Effect |
|---|---|
| `agents/<name>.append.md` | appended to the dpcli agent `<name>` — preferred, the agent keeps receiving updates |
| `agents/<name>.md` | an own agent, or a full replacement of the dpcli agent with that name (listed by `dpcli agents` as source `local`) |
| `skills/<name>/` | a project skill; replaces a dpcli skill with the same name |
| `workflow.md` | appended to the process description as "Project rules" |
| `claude-md.md` | appended to the dpcli block in `CLAUDE.md` |
| `feedback.jsonl` | friction ledger |

`init` creates `.dpcli-local/README.md` once.

## Self-improvement

| Command | Does |
|---|---|
| `feedback [--since D] [--module M] [--all]` | frictions from `dp_feedback`, `harness:` notes and review `harness`: clusters F-n (open/fixed, `⚠N after fix`) and unclustered by topic |
| `feedback show F-n\|TOPIC` | unique texts ×count with task IDs |
| `feedback new "title" --match REGEX --scope project\|dpcli [--why]` | create a cluster F-n (ledger `.dpcli-local/feedback.jsonl`) |
| `feedback fix F-n --where … [--pr URL]` · `wontfix F-n --why …` · `reopen F-n` | close / reject / reopen |
| `stats [module] [--since D] [--tokens]` | tasks, created→accepted, rework rounds, frictions; check durations (median/max s); `--tokens`: context tokens of executors, reviewers and coordinators and per task, from Claude Code's subagent logs |
| `contribute F-n [--title T] [--new]` | dpcli-scope fix from `.dpcli` branch `improve/*` → PR to the hub (origin or fork), or +1 on a similar open one; no commits → issue; no `gh` → `build/dpcli/contribute-F-n/` with issue text and patches |

## Updating automatically

`init` adds a Claude Code `SessionStart` hook: `.dpcli/dpcli update --auto` — at most once a day, silent when nothing happened.

`update` works in the main copy only. It fetches the hub, moves the `.dpcli` submodule to the latest release tag `vN` (never to a branch), runs `init` (the project layer `.dpcli-local/` is applied again) and commits `.dpcli`, `.claude/` and `CLAUDE.md` with the message `dpcli vN`, printing the CHANGELOG lines of the new releases. It skips, with one line of explanation, when `.dpcli` has uncommitted changes, is on an `improve/*` branch, has local commits on `main`, or the network is down.

It also checks the PRs and issues this project sent with `contribute`: merged → the cluster is marked fixed; `rework` or rejected → the reviewer's arguments go into the ledger and `harness-retro` decides whether to rework or drop.

| Flag | |
|---|---|
| `--check` | only say whether a new version is available |
| `--pin vN` / `--unpin` | never update above vN (`.dpcli-local/update.json`, committed) |
| `--prs-only` | only check own PRs/issues |

## Long checks

`accept` remembers how long each check took (`<log_dir>/<ID>/results.json`). When the same checks took longer than `checks.bg_after` seconds last time (default 100; 0 — never), `accept` runs itself as a background job and prints the wait command (`job wait dp-accept-<ID> <timeout>`); `--fg` stays in the foreground. A check's own timeout: `task new|set … --check-timeout NAME SEC` (default 900). `lock cpu|gpu` runs the command in the foreground with its output (`--tmux` for a window). Job names are per copy (`<copy>~<name>`), so two copies starting `acc` do not collide; `job wait <name>` from the same copy finds its job.

## Config

`dpcli.json` or `dpcli.yml`/`dpcli.yaml` at the project root (searched upward from the current directory to the git root; json wins if both exist). All keys are optional. Full list with comments and defaults — [`dpcli.example.yml`](../dpcli.example.yml). In brief:

- `project`, `main_branch`, `protect_main` (`false`; `true` — merge into `main_branch` only with an explicit `--into`), `module_branch` (`feature/{module}`), `task_branch` (`{module}/{task}`);
- `copies_dir`, `module_copy`, `task_copy` — where working copies are created (substitutions `{project}`, `{module}`, `{task}`, `{copies}`);
- `worktree` — preparing new copies (project-specific things go here: `copy` carries over ignored directories such as generator caches, `setup` is any preparation command) (see "Working copies"): `hooks` (`true`), `link` (`[node_modules]`), `copy` (`[.env, .env.*]`), `setup` (command), `setup_timeout` (1800 s);
- `plan_dir` (`docs/plan`), `contracts_dir` (`docs/contracts`), `docs_dir` (`docs`);
- `checks.env`, `checks.tests` (command template for `{tests: …}` checks, `{filter}`), `checks.log_dir` (`build/dpcli`);
- `artifacts_dir`, `reserved_codes`, `gc.ignore_dirs`, `gc.ignore_globs`;
- `sem` (`enabled: false` by default, `model`, `url`, `cache_dir`, `globs`), `jobs` (`dir`, `tmux_session`, `cpu_slots`), `locks`;
- `agents_dir` (`.dpcli/agents`), `workflow` (`.claude/dpcli-workflow.md`);
- `language` — `text` (language agents write in for people: replies, reports, journal, plans, docs) and `commits` (language of commit messages); codes `en`, `ru`, `de`, …; CLI output is always English;
- `roles` — roles of the project's own agents: `{name: {role: coordinator|executor|reviewer|status, review: bool}}`; the agent registry = `agents_dir` + `.claude/agents` with `dpcli_role` in frontmatter + `roles` (overrides); view with `dpcli agents`;
- `docs` (`extra`, `exclude`, `types`, `statuses`, `max_kb`, `max_kb_mode`, `summary_max`, `registries`).

## Agents

dpcli definitions live in `.dpcli/agents/*.md`: the Claude Code agent format (frontmatter `name, description, model, effort, tools/disallowedTools, skills`) plus dpcli keys:

- `dpcli_role`: `coordinator` | `executor` | `reviewer` | `status`;
- `dpcli_review`: `true` | `false` — whether a reviewer is needed after acceptance PASS (for executors).

Shipped: `dp-coordinator` (opus), `dp-engineer`, `dp-researcher`, `dp-writer` (sonnet), `dp-mechanic` (haiku), `dp-reviewer` (opus), `dp-status` (haiku). Agent texts are short; common rules live only in the process description, agents refer to it.

`init` fills in the placeholders `{{cli}}`, `{{workflow}}`, `{{plan_dir}}`, `{{contracts_dir}}`, `{{docs_dir}}`, `{{main_branch}}`, `{{module_branch}}`, `{{project}}` and puts the result in `.claude/agents/`. `init` does not touch project agents: a same-named file in `.claude/agents/` is skipped.

**Your own agents in process roles:** the `roles` key in `dpcli.yml` (agent name → `role`, `review`) or `dpcli_role`/`dpcli_review` in frontmatter. The executor type in `task new --type …` is validated against this registry; view it with `.dpcli/dpcli agents`.

```yaml
roles:
  my-designer: {role: executor, review: true}
```

**Models.** Executors — sonnet (mechanical work — haiku): with a clear card (goal, scope, dont_touch, checks with thresholds, contracts) that is enough. Opus — only if the task needs design that cannot be moved into the plan or a contract.

## Message protocol

Agents do not retell the journal; they pass IDs and a command, details are read with commands.

| From → to | Message |
|---|---|
| main → coordinator | `Module <m>: copy <path>, branch <branch>. Plan: dpcli plan <m>. New: dpcli inbox <m>.` |
| coordinator → executor | output of `task brief <ID>` as is (specifics go into the card via `task note`) |
| coordinator → reviewer | output of `task brief <ID> --review` as is |
| executor → coordinator | `<ID> reported` \| `<ID> blocked: <reason ≤15 words>` \| `<ID> contract: <what to change>` |
| reviewer → coordinator | `<ID> review accept` \| `<ID> review rework <n>` |
| coordinator → main | `<m>: <n> accepted, <n> in progress; gate Q<n>` or `<m> done` |
| main → user | free form, from `status` / `digest` |

User decisions reach the coordinator via `decide` → `inbox`, not by retelling. If information is missing — a one-line question. Details — in the process description (`.claude/dpcli-workflow.md`, section "Message protocol").

## Workflow

1. The **main session** (user + Claude) sits on the task's feature branch and creates a module: `.dpcli/dpcli module new payments --code PY --area web` — the module branch is created **from the feature branch** (the module base, recorded in `module.json`), plus a working copy and the journal `<plan_dir>/payments/`. It writes the plan (`<plan_dir>/payments/…`) and contracts.
2. It starts the module's **coordinator** (agent `dp-coordinator`) in the module copy.
3. The coordinator creates tasks:
   ```
   .dpcli/dpcli task new payments --type dp-engineer --title "Round the amount" \
     --goal "The amount is rounded to cents" --plan-ref "PY-1" \
     --scope src/money.py --test rounding \
     --check no_todo "grep -c TODO src/money.py" "re:^0$"
   .dpcli/dpcli task show PY-1          # card; --full — the full job for the executor
   .dpcli/dpcli event PY-1 started --note "dp-engineer"
   ```
   `task new` itself creates the task's working copy and branch (`<task_copy>` on `<task_branch>` from the module branch, with git-crypt and preparation — see "Working copies"; reuses them if present; `--no-copy` — do not create). Then the coordinator starts the **executor** with the message being the output of `.dpcli/dpcli task brief PY-1` as is (one task, its own copy).
4. The executor reads the plan by sections, works in its copy, does a trial run `accept PY-1 --dry` and submits a report:
   ```
   .dpcli/dpcli plan payments PY-1
   .dpcli/dpcli report --template PY-1 > r.json   # fill in
   .dpcli/dpcli report PY-1 < r.json
   ```
   The executor commits its own files on the task branch (`git commit -- <paths>`); branch merges belong to the coordinator and the main session (rules — `.claude/dpcli-workflow.md`).
5. The coordinator accepts: `.dpcli/dpcli accept PY-1 -j 4`. FAIL — back for rework; PASS for a type with `dpcli_review: true` — state `checked` (awaits review, `--no-review` — accepted right away), without review — `accepted`.
6. Review (a fresh `dp-reviewer`): `.dpcli/dpcli review PY-1 --verdict rework --from - < review.json`; the coordinator looks at `review PY-1 --show` and decides: `event PY-1 accepted --note "per review"` or rework.
7. Merge: task branch → module branch (in the module copy), `.dpcli/dpcli event PY-1 merged --commit <hash>`; fresh changes from the module base — `.dpcli/dpcli sync payments`; a finished module into its base (feature branch) — delivery: `.dpcli/dpcli deliver payments` (squash, journal → `decisions.md` and `summary.md`). Feature branch into `main_branch` — the user's decision (usually an MR); with `protect_main: true`, `deliver`/`merge` into it only with an explicit `--into` and only for a module created from it.
8. Cleanup: `.dpcli/dpcli gc` (list), `.dpcli/dpcli gc --remove`.

Observation: `.dpcli/dpcli status`, `digest --since today`, `log payments`, `questions`.

## Commands

Help for any subcommand — `.dpcli/dpcli <command> -h`. Event author — `--by`, else `$DPCLI_ROLE`, else derived from the copy's branch.

### Modules and branches

```
.dpcli/dpcli module new <module> [--from BRANCH] [--code PY] [--area A]   # branch from current (or --from) + copy + journal
.dpcli/dpcli module init <module> [--plan P] [--contracts C] [--branch B] [--copy C] [--code PY] [--area A] [--legacy PATH]   # journal only (--area — set/change)
.dpcli/dpcli sync <module|branch> [-m M] [--trailer T]          # merge the module base (feature branch) into the module branch (in its copy)
.dpcli/dpcli merge <branch|module> [--into BRANCH] [--push] [--no-index] [-m M] [--trailer T]   # --no-ff in the target's copy; default target: task → module branch, module → its base
.dpcli/dpcli deliver <module> [--into BRANCH] [-m M] [--force] [--dry]   # delivery: squash the module branch, journal → md
.dpcli/dpcli deliver <module> --in-place [--dry]                      # journal already in the current branch: collapse to md
.dpcli/dpcli deliver <module> --rerender [--from REF] [--area A] [--dry]   # delivered module: md regenerated from the journal at REF, no commit
.dpcli/dpcli gc [BRANCH|MODULE …] [--remove]                    # copies and branches already merged into main
.dpcli/dpcli copy setup [PATH]                                 # prepare a copy (hooks, env, node_modules) — idempotent
```

#### Working copies

`module new` and `task new` create a copy so that it is usable immediately:

1. `git worktree add --no-checkout`, then git-crypt keys from the shared `.git` are copied into the copy's GIT_DIR (`<common>/worktrees/<name>/git-crypt`; a copy, not a symlink) and only then checkout — otherwise the git-crypt smudge filter fails. Files that stay encrypted produce a warning with a `git crypt unlock` hint.
2. A failure at any creation step (checkout, journal, the `module new` commit) removes the copy and deletes the created branch: no branch is left without a copy.
3. Preparation (`worktree.*` in config; source — the main copy, the first in `git worktree list`):
   - `hooks: true` — a relative `core.hooksPath` (e.g. `.husky/_`, which is in `.gitignore` and empty after checkout) is copied over from the main copy, otherwise pre-commit silently does not work. `accept` does not count this directory as going outside `scope`;
   - git-ignored paths of the main copy (`git ls-files --others --ignored --directory`) by pattern: `link` — hard links via `cp -al` (copy on another filesystem), `copy` — a copy. A pattern without `/` matches by name at any depth, with `/` — a path from the root. Anything already present in the copy, or whose directory is absent from the branch, is skipped. An empty list (`link: []`) turns it off;
   - `setup` — a project command (`bash -c`, cwd — the new copy, env `DPCLI_COPY`, `DPCLI_MAIN_COPY`, `DPCLI_BRANCH`, timeout `setup_timeout`). A failure does not roll back the copy: the output tail and `copy setup` for a retry are printed.

Hard links share files with the main copy: `npm install` in a copy may affect them; if you change dependencies — `rm -rf node_modules && npm ci` in the copy. `copy setup [PATH]` repeats preparation on an existing copy (adds what is missing, does not overwrite your own files).

`sync`, `merge`, `task sync`: an uncommitted module journal in the target copy is committed automatically before the merge; any other "dirt" — refusal. On conflict the merge is aborted and a list of files is printed.

`gc` skips modules with open tasks and live `<module>/*` branches, dirty copies (changes in tracked files), copies with untracked work files, and copies referenced by symlinks; `--remove` does `git worktree remove` and `git branch -d`. Git-ignored files and generated ones (`gc.ignore_dirs` — any directory with that name at any depth, `gc.ignore_globs`) do not block removal: `--force` for `worktree remove` is added only when the untracked content consists entirely of this set. Paths with spaces and non-ASCII characters are read from git unquoted (`-z`, `core.quotepath=off`).

### Tasks

Task ID: `<CODE>-[stage]<n>[letter]` (`PY-7`, `PY-7a`, `PY-P8`); CODE is the module's `code` (2–4 uppercase Latin letters, unique). Without an ID, `task new` takes the module's next number (`--stage P` — the next `<CODE>-P<n>`).

```
.dpcli/dpcli task new <module> [ID] --type T --title "…" --goal "…" [--plan-ref "§1"] \
    [--stage P] [--copy C] [--branch B] [--contract NAME@VERSION] [--scope PATH] [--dont-touch PATH] \
    [--test FILTER] [--check NAME CMD EXPECT] [--from card.json|-] [--no-copy] [--force]
.dpcli/dpcli task show <ID> [--json] [--full] [--diff]
.dpcli/dpcli task brief <ID> [--review]   # ready-made message for the executor (reviewer) — send as is
.dpcli/dpcli agents                       # agent registry: name, role, review, source (dpcli|project|config), model
.dpcli/dpcli task set <ID> field=value field+=item field-=item [--check NAME CMD EXPECT] [--test F] [--drop-check NAME] [--contract NAME@VERSION]
.dpcli/dpcli task note <ID> "rule or note"   # addendum to an issued task (visible in task show and inbox <ID>)
.dpcli/dpcli task sync <ID> [--message M] [--trailer T]   # merge the module branch into the task branch in its copy
```

The card (`<plan_dir>/<module>/tasks/<ID>.json`) is plain JSON: `id, module, type, title, goal, plan_ref, contracts[], copy, branch, base, scope[], dont_touch[], accept[], report_extra[], notes`; it can be edited by hand. A contract `<name>.Cx` with another module's name (`billing.C5`) points in `task show` to `<contracts_dir>/<name>.md`, not to the current module's contracts file. `task set` order: `--drop-check` first, then `--check`/`--test` (replace a check in one call); a value is JSON or a string, and for list fields a string is a comma-separated list.

`task brief` refuses (exit 1, list of what is missing) if the card has no `goal`, no `scope` or no checks at all — the card is not ready to be issued; `task new` warns about such gaps. A check's `EXPECT` is parsed immediately in `task new`/`task set` (invalid — refusal).

An acceptance check is `{name, cmd, expect, cwd?, timeout?}` or `{name, tests: "<filter>"}` (command from `checks.tests`). `EXPECT`:

- `exit=0` (default);
- `re:<regex>` — present in the output; `!re:<regex>` — absent from the output;
- `num:<regex with a group> <op><number>`, op: `<= >= == < >` — the last match, a comma is read as a dot;
- `tests` — check with the project's tests;
- an object: `{"exit":0, "re":"…", "num":"…", "min":…, "max":…}` — all conditions at once.

Commands run via `bash -c` in the task's copy (if there is one; `--here` — in the current one); default timeout 900 s; `$DPCLI_TASK` is in the environment.

### Events, decisions, questions

```
.dpcli/dpcli event <ID|module> started|reported|accepted|merged|blocked|cancelled|note [--commit h] [--note "…"]
.dpcli/dpcli decide <module> "decision" --by user|coordinator|main [--why "…"] [--task ID] [--plan [SECTION]]
.dpcli/dpcli decide <module> "question" --ask             # gate: question to the user → Q1
.dpcli/dpcli decide <module> "answer" --by user --answers Q1
.dpcli/dpcli answer <Qn|module/Qn> "answer" [--module M]  # = decide --by user --answers Qn
.dpcli/dpcli questions [--all] [--module M] [--full]     # open questions across all modules
.dpcli/dpcli inbox <module|ID> [--by reader] [--peek] [--max N] [--full]
.dpcli/dpcli log <module|ID> [-n N] [--full] [--no-decisions]
```

`--plan` on `decide` appends a line to a plan section ("User decisions" by default). `inbox` shows what is new since this reader last read (decisions, answers, plan edits, notes); the reader is `--by`, else `$DPCLI_ROLE`, else `coordinator` (for an ID — `executor`). The read marker is `<plan_dir>/<module>/.read_<reader>` (in `.gitignore`).

### Acceptance, report, review

```
.dpcli/dpcli accept <ID> [--only NAME] [--here|--cwd DIR] [-j 4] [--commit h] [--dry] [--no-accept] [--no-review] [--full] [--bg [--timeout SEC]] [--no-tmux] [--tmux-session S]
.dpcli/dpcli report <ID> [file|-]  |  report <ID> --show [--full]  |  report --template [ID]
.dpcli/dpcli review <ID> --verdict accept|rework --from r.json|-  |  review <ID> --note "summary"  |  review <ID> --show [--full]  |  review --template
```

`accept` prints a `PASS/FAIL name value` table, with the log path (`checks.log_dir/<ID>/`) for FAIL. All PASS → event `accepted`, otherwise `checked` with the result. For types with `dpcli_review: true`, PASS → `checked` (awaits review; `--no-review` — `accepted` right away; `--here` after a merge does not wait for review). `--dry` — trial run without an event; `--only` — one check (a summary of all at the end); `--bg` — via `job` (long checks), wait with `.dpcli/dpcli job wait dp-accept-<ID> <sec>`.

The `scope` row in the table is a deterministic boundary check: files changed in the task branch relative to `base` (`git diff --name-only base...HEAD` + uncommitted) must fall within `scope` and must not fall within `dont_touch` (an entry is a glob or a file/directory prefix; the path may contain spaces: it is taken whole if the explanation is separated by ` — `, ` - `, ` (` or `: `, or the path is in backticks; without an explanation the whole line and the first word both work). A violation is FAIL with a list of files (up to 10). Empty `scope` or a copy not on the task branch — `SKIP`. The module journal (`<plan_dir>/<module>/`, including the report), `checks.log_dir` and `gc.ignore_*` do not count as violations.

Report (`report --template`): `status` (done|partial|blocked|failed), `summary`, `commits[]`, `checks[{name, value, pass}]`, `not_done[]`, `questions[]`, `images[]`, `how_to_check`, `uncertain`, `dp_feedback`, plus the card's `report_extra` keys. An invalid report is not saved; the error says what is wrong.

Review (`review --template`): `verdict` accept|rework, `summary`, `issues[]` (≤ 7) `{file, line, severity: blocker|major|minor, what, fix}`, `rerun[{name, value, pass}]`. A blocker with accept is an error.

### Plan, status, journal

```
.dpcli/dpcli plan <module|file.md> [<number|heading start>] [--contracts] [--depth 3] [--max 150]   # table of contents or a section
.dpcli/dpcli plan edit <module|file.md> <section> --append "text" | --replace OLD NEW [--all] | --set [FILE|-]  [--contracts] [--commit]
.dpcli/dpcli status [<module>] [--full] [--stale 40] [--since 30m|2h|today]
.dpcli/dpcli digest [--since today|DATE|2h]
.dpcli/dpcli render <module> [--out path|-] [--force]    # md journal <plan_dir>/<module>/journal.md
```

`plan edit --replace` requires exactly one occurrence in the section (`--all` — all of them); section `*` is the whole file (`--replace` only); `--set` without a file or with `-` reads stdin. `status`: "quiet" — no events and no task-branch commits for longer than the threshold (min).

### Search

```
.dpcli/dpcli search <text|regex> [--module M] [--max N]       # over cards, reports, events, decisions of all modules
.dpcli/dpcli search --sem "query" [--max 10] [--module M|--path PREFIX] [--all]
.dpcli/dpcli index [--full]                                    # semantic index
```

Before new work it is useful to `search` past modules. Semantic search is optional and off by default (`sem.enabled: false`): without it `search --sem` and `index` report that search is disabled, and `merge` into the main branch does not update the index. To enable: `sem.enabled: true` in the config, install Ollama and `ollama pull bge-m3`, then `.dpcli/dpcli index`.
When enabled, embeddings go through Ollama (`sem.url`, `sem.model`, bge-m3 by default; `ollama pull bge-m3` once). The index lives outside git in `sem.cache_dir` and is updated by text hash. `DPCLI_SEM_CPU=1` — compute on CPU only. The corpus is `sem.globs` and dpcli journals. No Ollama or model — an error with a hint.

### Documentation

```
.dpcli/dpcli docs check [path …]                              # frontmatter, summary, live links, size (exit 1 on errors); with paths — only those files (a directory — all documents under it)
.dpcli/dpcli docs index                                       # build INDEX.md and registries (docs.registries)
.dpcli/dpcli docs find [--type T] [--status S] [--module M] [--archive] [--long] [text]   # one "path — summary" line per document
.dpcli/dpcli docs section <path>[#section] [<number|heading start>] [--depth 3] [--max N]  # table of contents or a section
.dpcli/dpcli docs show <path.md>                              # frontmatter + table of contents
.dpcli/dpcli docs findings [--module M] [text]                # findings from registry/findings.md
.dpcli/dpcli docs init [--dry] [--refresh-contracts]          # frontmatter for files without it (summary: "TODO")
```

Documentation is read piece by piece: `INDEX.md` is the entry point (modules by `area`, one line per module: plan summary, status and date, links to the plan, contracts, decisions, summary and journal archive, below it the module's other documents; the rest are groups by type, one line per document `- [path](path) — summary [status]`, the archive on one line), `docs find` — one line per document, `docs section` — a document's table of contents (without a section) or the text of a section with its subsections, without frontmatter. A section is a number from the table of contents or a heading start; if several match — a list of candidates and exit 1 (`plan` resolves sections the same way).

Frontmatter is read as YAML (`related` lists — block `- a` and inline `[a, b]`). `docs check` rules: `summary` is required, a single line ≤ `docs.summary_max` (140) characters, `TODO` is an error (`docs init` sets `summary: "TODO"` rather than inventing one from the text); a document larger than `docs.max_kb` (40 KB) is an error with a hint to split it into section files or move data out (`docs.max_kb_mode: warn` — a warning only; archive and `generated: true` are not checked). `docs find --status closed|superseded` and `--archive` also search `{docs_dir}/archive/`.

Registries: `docs.registries` (default `[research, contracts]`; `decisions` only if enabled explicitly, otherwise decisions are found with `search`). `registry/findings.md` is written by hand (`docs index` creates a stub): a `## <module>` section, a finding is a one-line `- …` item with numbers and a `path#section` link. Allowed `type`/`status`, exclusions and limits — the `docs` section of the config.

### Long runs and locks

```
.dpcli/dpcli job start <name> <timeout_s> <command…>     # in the background; rc is always written, 124 — timeout
.dpcli/dpcli job wait <name> <timeout_s>                  # waits, prints the code and log tail
.dpcli/dpcli job status [name] [--all]  |  job stop <name>  |  job attach <name>
.dpcli/dpcli job --lock cpu|gpu start <name> <timeout_s> <command…>
.dpcli/dpcli lock cpu|gpu <name> [--timeout SEC] -- <command…>
.dpcli/dpcli lock status
```

Logs — `<jobs.dir>/<name>.{pid,log,rc}`; `rc`: 124 — timeout, 143 — `job stop`, 129 — window closed by the user. The `cpu` lock has N slots (`jobs.cpu_slots` / `DPCLI_CPU_SLOTS`, default half the logical cores), `gpu` has one. A tmux window is used by default (session `$DPCLI_TMUX_SESSION`, else `jobs.tmux_session`); `--no-tmux` — background only; no tmux — a warning and a plain background run. The window closes when the job finishes. Inside tasks tmux is disabled (`DPCLI_NO_TMUX=1`).

## Delivering a module

The journal is working material of the module branch and does not go into the final branch. `deliver <module>`:

1. refuses if there are unaccepted tasks or unanswered questions (`--force` — deliver as is), or if the module copy or the target copy is dirty;
2. commits the journal in the module copy, runs `git merge --squash <module branch>` in the final branch's copy (`--into`, default the module base); a conflict only in `INDEX.md`/registries is rebuilt automatically, otherwise rollback — `sync` first;
3. removes everything from `<plan_dir>/<module>/` except `deliver.keep` (default `decisions.md`, `summary.md`) and writes these files from the journal:
   - `decisions.md` — questions with answers (the answer under the question) and decisions by author, with the "why"; dates `YYYY-MM-DD` without time; a user decision without a reason (or with only a source reference such as "user answer 2026-10-09") is marked "approved by the developer";
   - `summary.md` — per task: result (the report's `summary`), status and review verdict, "not done", "not sure", executor's questions;
4. one commit "<module>: <plan title>" with the task list in the body — through hooks (pre-commit checks the whole module); if it fails, the changes stay in the index;
   both files get `area` of the module and `archive` (the tag with the full journal, if `deliver.archive_tag` is set) in frontmatter;
   the module's plan and contracts (`module` in frontmatter) → `status: closed`, `updated`, `area`; `INDEX.md` and registries are rebuilt (`docs index`) — all in the same commit;
5. an event `delivered` in the module journal and a tag `deliver.archive_tag` (`archive/{module}`; `false` — no tag, then `archive` is not written into md either) on the module branch — the full journal stays there.

After delivery, do not continue the module branch: a repeated squash does not know what is already merged. Rework is a new task or a module from the final branch.

`--in-place` — for journals already merged into the current branch by a plain merge: writes the same md (`archive` — the last commit with the journal) and deletes the rest in one commit.

`--rerender` — the module is already delivered but the md format changed: the journal is taken from `--from` (tag or commit; default `deliver.archive_tag`) via `git archive`, md is rewritten, the plan and contracts are closed, the index is rebuilt; the commit is up to you. An old journal without `area` — `--area`.

## Journal storage

`<plan_dir>/<module>/`:

- `module.json` — the module: code, area, branch, copy, plan, contracts;
- `tasks/<ID>.json` — card, `tasks/<ID>.report.json` — executor's report, `tasks/<ID>.review.json` — latest review;
- `events.jsonl` — events (append-only): `{t, by, task, ev, commits?, note?}`;
- `decisions.jsonl` — decisions and questions: `{t, by, kind: decision|question, text, why?, id?, answers?}`;
- `.read_<reader>` — inbox read markers (outside git);
- `journal.md` — result of `render`;
- `decisions.md`, `summary.md` — result of `deliver` (after delivery only these remain in the final branch).

**Journal home** is the working copy of the module branch if the module's journal is there; otherwise the current copy. So `dpcli` from any copy (main, module, task) reads and writes one journal. The coordinator commits it. `DPCLI_LOCAL=1` — current copy only. dpcli commits nothing itself (except the journal before a merge and `plan edit --commit`).

## Environment variables

| Variable | Purpose |
|---|---|
| `DPCLI_ROLE` | default event author and inbox reader (`main`, `coordinator`, `executor`, …) |
| `DPCLI_LOCAL` | `1` — journal of the current copy only |
| `DPCLI_NO_REEXEC` | `1` — do not re-exec from the main copy |
| `DPCLI_SESSION` | session identifier for the line in commit messages |
| `DPCLI_TASK` | ID of the current task (set inside checks) |
| `DPCLI_COPIES` | working copies directory instead of `copies_dir` |
| `DPCLI_CPU_SLOTS` | number of cpu lock slots |
| `DPCLI_NO_TMUX` | `1` — do not open tmux windows |
| `DPCLI_TMUX_SESSION` | tmux session for windows |
| `DPCLI_JOB_DIR` | `job` runs directory instead of `jobs.dir` |
| `DPCLI_SEM_CPU` | `1` — embeddings on CPU only |

`DPCLI_REEXECED` is internal (guards against repeated re-exec).

## Exit codes

- `0` — success;
- `1` — error or a failed check (FAIL);
- `2` — invalid arguments.

For `job`/`lock` the exit code is the command's own (124 — timeout).

## Updating dpcli in a project

1. Submodule: `git -C .dpcli pull` (or `checkout <version>`), then `git add .dpcli` and a project commit. Copy: replace the `.dpcli` contents with the new version (keep or carry over your own files in `.dpcli/agents`).
2. Run `.dpcli/dpcli init` (or `init --check` to see what changed; `--force` — overwrite hand-edited files).
3. The version is `VERSION` in `.dpcli/lib/dpcli/__init__.py` (`.dpcli/dpcli --version`).

A stale `.dpcli` in a task's working copy re-execs itself from the main copy (`<main worktree>/.dpcli/dpcli`) if its `VERSION` is newer: one line on stderr, arguments and cwd are preserved. Disable with `DPCLI_NO_REEXEC=1`. So updating the main copy is enough.

## Developing dpcli

The repository root is the distribution itself (in a project it lives as `.dpcli`): entry point `dpcli`, package `lib/dpcli`, `agents/`, `skills/`, `templates/`, `dpcli.example.yml`. Also: `tests/` (unittest, `python3 -m unittest discover -s tests`), [CLAUDE.md](../CLAUDE.md) — working rules, [ROADMAP.md](../ROADMAP.md) — plan, [CHANGELOG.md](../CHANGELOG.md) — changes by version.
