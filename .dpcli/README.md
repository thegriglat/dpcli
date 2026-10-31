# dpcli — journal, task cards and acceptance

Process tool for "main session ↔ module coordinator ↔ executors ↔ reviewer" in projects run by Claude Code agents. Keeps module journals (task cards, reports, events, decisions, questions to the user), manages branches and working copies (git worktree), runs acceptance checks and merges branches. Output is short; details — `--full`.

Exit codes: 0 — ok, 1 — error or FAIL, 2 — bad arguments. An error is one line `dpcli: …`.

## Requirements

- python3 ≥ 3.10 (stdlib only; PyYAML is optional — a built-in parser for a YAML subset is included);
- git;
- optional: tmux (windows for `job`/`lock`/`accept --bg`); Ollama with the `bge-m3` model is needed only for semantic search (`search --sem`, `index`) and is off by default.

## Installation

1. Copy the `.dpcli` directory into the root of a git project.
2. Run `.dpcli/dpcli init`.

`init` creates (all idempotent):

| What | Where |
|---|---|
| Config from the example (if there is no config) | `dpcli.yml` |
| Agents with placeholders filled in | `.claude/agents/*.md` |
| Skills | `.claude/skills/<name>/SKILL.md` |
| Workflow description | `.claude/dpcli-workflow.md` |
| Block between markers `<!-- dpcli:begin -->` … `<!-- dpcli:end -->` | `CLAUDE.md` |
| Permission `Bash(.dpcli/dpcli *)` | `.claude/settings.json` |
| Lines `.read_*`, `build/dpcli/` | `.gitignore` |

`init` modes:

- rerunning is safe: nothing changes if the result is up to date; what `init` wrote is tracked in `.claude/.dpcli-manifest.json`; such files edited by hand are not overwritten without `--force` — a message is printed;
- project files (not in the manifest) are never overwritten or removed by `init`, even with `--force`: if `.claude/agents` already has an agent with a dpcli agent's name, the dpcli agent is skipped ("skipped — project agent; role: see roles in config"); same for a skill with the same name and the workflow file. `CLAUDE.md` and `settings.json` get targeted inserts (block between markers, one permission);
- `--force` — overwrite/remove hand-edited files from the manifest;
- `--check` — only check whether setup is up to date (writes nothing);
- `--dry-run` — show what would be done;
- `--json` | `--yaml` — config format, if it is created (default `dpcli.yml`).

Exact flags: `.dpcli/dpcli init -h`.

After `init`, commit the result (only the main session commits).

## Config

`dpcli.json` or `dpcli.yml`/`dpcli.yaml` in the project root (searched upward from the current directory to the git root; if both exist, json wins). All keys are optional. Full list with comments and defaults — [`dpcli.example.yml`](dpcli.example.yml). In short:

- `project`, `main_branch`, `protect_main` (`false`; `true` — into `main_branch` only with explicit `--into`), `module_branch` (`feature/{module}`), `task_branch` (`{module}/{task}`);
- `copies_dir`, `module_copy`, `task_copy` — where working copies are created (substitutions `{project}`, `{module}`, `{task}`, `{copies}`);
- `worktree` — setup of new copies (project specifics go here: `copy` carries ignored directories such as generator caches, `setup` — any setup command) (see "Working copies"): `hooks` (`true`), `link` (`[node_modules]`), `copy` (`[.env, .env.*]`), `setup` (command), `setup_timeout` (1800 s);
- `plan_dir` (`docs/plan`), `contracts_dir` (`docs/contracts`), `docs_dir` (`docs`);
- `checks.env`, `checks.tests` (command template for `{tests: …}` checks, `{filter}`), `checks.log_dir` (`build/dpcli`);
- `artifacts_dir`, `reserved_codes`, `gc.ignore_dirs`, `gc.ignore_globs`;
- `sem` (`enabled: false` by default, `model`, `url`, `cache_dir`, `globs`), `jobs` (`dir`, `tmux_session`, `cpu_slots`), `locks`;
- `agents_dir` (`.dpcli/agents`), `workflow` (`.claude/dpcli-workflow.md`);
- `roles` — roles of your own project agents: `{name: {role: coordinator|executor|reviewer|status, review: bool}}`; agent registry = `agents_dir` + `.claude/agents` with `dpcli_role` in frontmatter + `roles` (overrides); view — `dpcli agents`;
- `docs` (`extra`, `exclude`, `types`, `statuses`, `max_kb`, `max_kb_mode`, `summary_max`, `registries`).

## Agents

dpcli definitions — `.dpcli/agents/*.md`: Claude Code agent format (frontmatter `name, description, model, effort, tools/disallowedTools, skills`) plus dpcli keys:

- `dpcli_role`: `coordinator` | `executor` | `reviewer` | `status`;
- `dpcli_review`: `true` | `false` — whether a reviewer is needed after acceptance PASS (for executors).

Shipped: `dp-coordinator` (opus), `dp-engineer`, `dp-researcher`, `dp-writer` (sonnet), `dp-mechanic` (haiku), `dp-reviewer` (opus), `dp-status` (haiku). Agent texts are short; shared rules live only in the workflow description, agents refer to it.

Placeholders `{{cli}}`, `{{workflow}}`, `{{plan_dir}}`, `{{contracts_dir}}`, `{{docs_dir}}`, `{{main_branch}}`, `{{module_branch}}`, `{{project}}` are filled in by `init`, which puts the result into `.claude/agents/`. `init` doesn't touch project agents: a same-name file in `.claude/agents/` is skipped.

**Your own agents in process roles:** the `roles` key in `dpcli.yml` (agent name → `role`, `review`) or `dpcli_role`/`dpcli_review` in frontmatter. The executor type in `task new --type …` is validated against this registry; view it — `.dpcli/dpcli agents`.

```yaml
roles:
  my-designer: {role: executor, review: true}
```

**Models.** Executors — sonnet (mechanical work — haiku): with a clear card (goal, scope, dont_touch, checks with thresholds, contracts) that is enough. Opus — only if the task needs design that can't be moved into the plan or contract.

## Message protocol

Agents don't retell the journal; they pass an ID and a command; details are read via commands.

| From → to | Message |
|---|---|
| main → coordinator | `Module <m>: copy <path>, branch <branch>. Plan: dpcli plan <m>. New: dpcli inbox <m>.` |
| coordinator → executor | output of `task brief <ID>` as is (specifics go into the card via `task note`) |
| coordinator → reviewer | output of `task brief <ID> --review` as is |
| executor → coordinator | `<ID> reported` \| `<ID> blocked: <reason ≤15 words>` \| `<ID> contract: <what to change>` |
| reviewer → coordinator | `<ID> review accept` \| `<ID> review rework <n>` |
| coordinator → main | `<m>: <n> accepted, <n> in progress; gate Q<n>` or `<m> done` |
| main → user | free form, from `status` / `digest` |

User decisions reach the coordinator via `decide` → `inbox`, not by retelling. Missing information — a one-line question. Details — in the workflow description (`.claude/dpcli-workflow.md`, section "Message protocol").

## Workflow

1. The **main session** (user + Claude) is on the task's feature branch and creates a module: `.dpcli/dpcli module new payments --code PY --area web` — module branch **from the feature branch** (module base, stored in `module.json`), working copy and journal `<plan_dir>/payments/`. It writes the plan (`<plan_dir>/payments/…`) and contracts.
2. It launches the module **coordinator** (agent `dp-coordinator`) in the module copy.
3. The coordinator creates tasks:
   ```
   .dpcli/dpcli task new payments --type dp-engineer --title "Amount rounding" \
     --goal "Amount is rounded to cents" --plan-ref "PY-1" \
     --scope src/money.py --test rounding \
     --check no_todo "grep -c TODO src/money.py" "re:^0$"
   .dpcli/dpcli task show PY-1          # card; --full — full executor brief
   .dpcli/dpcli event PY-1 started --note "dp-engineer"
   ```
   `task new` creates the task's working copy and branch itself (`<task_copy>` on `<task_branch>` from the module branch, with git-crypt and setup — see "Working copies"; reuses an existing one; `--no-copy` — don't create). Then the coordinator launches the **executor** with a message — the output of `.dpcli/dpcli task brief PY-1` as is (one task, its own copy).
4. The executor reads the plan by section, works in its copy, does a dry run `accept PY-1 --dry` and submits a report:
   ```
   .dpcli/dpcli plan payments PY-1
   .dpcli/dpcli report --template PY-1 > r.json   # fill in
   .dpcli/dpcli report PY-1 < r.json
   ```
   The executor commits its own files in the task branch (`git commit -- <paths>`); branch merges are done by the coordinator and the main session (rules — `.claude/dpcli-workflow.md`).
5. The coordinator accepts: `.dpcli/dpcli accept PY-1 -j 4`. FAIL — back for rework; PASS for a type with `dpcli_review: true` — state `checked` (awaits review, `--no-review` — accepted right away), without review — `accepted`.
6. Review (fresh `dp-reviewer`): `.dpcli/dpcli review PY-1 --verdict rework --from - < review.json`; the coordinator looks at `review PY-1 --show` and decides: `event PY-1 accepted --note "by review"` or rework.
7. Merge: task branch → module branch (in the module copy), `.dpcli/dpcli event PY-1 merged --commit <hash>`; fresh changes from the module base — `.dpcli/dpcli sync payments`; finished module into the base (feature branch) — delivery: `.dpcli/dpcli deliver payments` (squash, journal → `decisions.md` and `summary.md`). Feature branch into `main_branch` — by user decision (usually an MR); with `protect_main: true`, `deliver`/`merge` there — only with explicit `--into` and only for a module created from it.
8. Cleanup: `.dpcli/dpcli gc` (list), `.dpcli/dpcli gc --remove`.

Monitoring: `.dpcli/dpcli status`, `digest --since today`, `log payments`, `questions`.

## Commands

Help for any subcommand — `.dpcli/dpcli <command> -h`. Event author — `--by`, else `$DPCLI_ROLE`, else inferred from the copy's branch.

### Modules and branches

```
.dpcli/dpcli module new <module> [--from BRANCH] [--code PY] [--area A]   # branch from current (or --from) + copy + journal
.dpcli/dpcli module init <module> [--plan P] [--contracts C] [--branch B] [--copy C] [--code PY] [--area A] [--legacy PATH]   # journal only (--area — set/change)
.dpcli/dpcli sync <module|branch> [-m M] [--trailer T]          # merge module base (feature branch) into module branch (in its copy)
.dpcli/dpcli merge <branch|module> [--into BRANCH] [--push] [--no-index] [-m M] [--trailer T]   # --no-ff in target copy; default target: task → module branch, module → its base
.dpcli/dpcli deliver <module> [--into BRANCH] [-m M] [--force] [--dry]   # delivery: squash module branch, journal → md
.dpcli/dpcli deliver <module> --in-place [--dry]                      # journal already in current branch: fold into md
.dpcli/dpcli deliver <module> --rerender [--from REF] [--area A] [--dry]   # delivered module: md again from journal in REF, no commit
.dpcli/dpcli gc [BRANCH|MODULE …] [--remove]                    # copies and branches already merged into main
.dpcli/dpcli copy setup [PATH]                                 # set up a copy (hooks, env, node_modules) — idempotent
```

#### Working copies

`module new` and `task new` create a copy so that it is usable right away:

1. `git worktree add --no-checkout`, then git-crypt keys from the shared `.git` are copied into the copy's GIT_DIR (`<common>/worktrees/<name>/git-crypt`; as a copy, not a symlink) and only then checkout — otherwise the git-crypt smudge filter fails. Files left encrypted — a warning with a `git crypt unlock` hint.
2. Failure at any creation step (checkout, journal, `module new` commit) — the copy is removed and the created branch deleted: no branch without a copy is left behind.
3. Setup (`worktree.*` in config; source — the main copy, first in `git worktree list`):
   - `hooks: true` — a relative `core.hooksPath` (e.g. `.husky/_`, which is in `.gitignore` and empty after checkout) is copied from the main copy, otherwise pre-commit silently doesn't run. `accept` doesn't count this directory as going outside `scope`;
   - git-ignored paths of the main copy (`git ls-files --others --ignored --directory`) by pattern: `link` — hard links `cp -al` (on another FS — a copy), `copy` — a copy. Pattern without `/` — by name at any depth, with `/` — path from root. Already present in the copy or parent dir missing in the branch — skipped. An empty list (`link: []`) disables;
   - `setup` — project command (`bash -c`, cwd — the new copy, env `DPCLI_COPY`, `DPCLI_MAIN_COPY`, `DPCLI_BRANCH`, timeout `setup_timeout`). A failure doesn't roll back the copy: the output tail and `copy setup` for a retry are printed.

Hard links share files with the main copy: `npm install` in the copy may affect them; changing dependencies — `rm -rf node_modules && npm ci` in the copy. `copy setup [PATH]` repeats setup on an existing copy (adds what's missing, doesn't overwrite its own files).

`sync`, `merge`, `task sync`: an uncommitted module journal in the target copy is committed automatically before merging; any other uncommitted changes — refusal. Conflict — the merge is aborted and the file list printed.

`gc` skips modules with open tasks and live `<module>/*` branches, dirty copies (changes in tracked files), copies with untracked work files and copies referenced by symlinks; `--remove` runs `git worktree remove` and `git branch -d`. Git-ignored files and generated output (`gc.ignore_dirs` — any directory with that name at any depth, `gc.ignore_globs`) don't block removal: `--force` is added to `worktree remove` only when everything untracked belongs to that set. Paths with spaces and non-ASCII characters are read from git unquoted (`-z`, `core.quotepath=off`).

### Tasks

Task ID: `<CODE>-[stage]<n>[letter]` (`PY-7`, `PY-7a`, `PY-P8`); CODE — the module `code` (2–4 uppercase Latin letters, unique). Without an ID `task new` takes the module's next number (`--stage P` — next `<CODE>-P<n>`).

```
.dpcli/dpcli task new <module> [ID] --type T --title "…" --goal "…" [--plan-ref "§1"] \
    [--stage P] [--copy C] [--branch B] [--contract NAME@VERSION] [--scope PATH] [--dont-touch PATH] \
    [--test FILTER] [--check NAME CMD EXPECT] [--from card.json|-] [--no-copy] [--force]
.dpcli/dpcli task show <ID> [--json] [--full] [--diff]
.dpcli/dpcli task brief <ID> [--review]   # ready message for the executor (reviewer) — send as is
.dpcli/dpcli agents                       # agent registry: name, role, review, source (dpcli|project|config), model
.dpcli/dpcli task set <ID> field=val field+=item field-=item [--check NAME CMD EXPECT] [--test F] [--drop-check NAME] [--contract NAME@VERSION]
.dpcli/dpcli task note <ID> "rule or note"   # addendum to an issued task (visible in task show and inbox <ID>)
.dpcli/dpcli task sync <ID> [--message M] [--trailer T]   # merge module branch into task branch in its copy
```

Card (`<plan_dir>/<module>/tasks/<ID>.json`) — plain JSON: `id, module, type, title, goal, plan_ref, contracts[], copy, branch, base, scope[], dont_touch[], accept[], report_extra[], notes`; can be edited by hand. A contract `<name>.Cx` with another module's name (`billing.C5`) points in `task show` to `<contracts_dir>/<name>.md`, not to the current module's contracts file. `task set` order: `--drop-check` first, then `--check`/`--test` (replace a check in one call); value — JSON or a string, for list fields a string is a comma-separated list.

`task brief` refuses (exit 1, list of what's missing) if the card has no `goal`, `scope` or any check — the card isn't ready to be issued; `task new` warns about such gaps. Check `EXPECT` is parsed right away in `task new`/`task set` (invalid — refusal).

Acceptance check — `{name, cmd, expect, cwd?, timeout?}` or `{name, tests: "<filter>"}` (command from `checks.tests`). `EXPECT`:

- `exit=0` (default);
- `re:<regex>` — present in output; `!re:<regex>` — absent from output;
- `num:<regex with group> <op><number>`, op: `<= >= == < >` — last match, comma is read as a decimal point;
- `tests` — check via project tests;
- object: `{"exit":0, "re":"…", "num":"…", "min":…, "max":…}` — all conditions at once.

Commands run via `bash -c` in the task copy (if any; `--here` — in the current one); default timeout 900 s; `$DPCLI_TASK` is set in the environment.

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

`--plan` on `decide` appends a line to a plan section ("User decisions" by default). `inbox` shows what's new since this reader's last read (decisions, answers, plan edits, notes); reader — `--by`, else `$DPCLI_ROLE`, else `coordinator` (for an ID — `executor`). Read marker — `<plan_dir>/<module>/.read_<reader>` (in `.gitignore`).

### Acceptance, report, review

```
.dpcli/dpcli accept <ID> [--only NAME] [--here|--cwd DIR] [-j 4] [--commit h] [--dry] [--no-accept] [--no-review] [--full] [--bg [--timeout SEC]] [--no-tmux] [--tmux-session S]
.dpcli/dpcli report <ID> [file|-]  |  report <ID> --show [--full]  |  report --template [ID]
.dpcli/dpcli review <ID> --verdict accept|rework --from r.json|-  |  review <ID> --note "summary"  |  review <ID> --show [--full]  |  review --template
```

`accept` prints a table `PASS/FAIL name value`, with the log path for FAIL (`checks.log_dir/<ID>/`). All PASS → event `accepted`, otherwise `checked` with the result. For types with `dpcli_review: true` PASS → `checked` (awaits review; `--no-review` — `accepted` right away; `--here` after merge doesn't wait for review). `--dry` — dry run without an event; `--only` — one check (summary of all at the end); `--bg` — via `job` (long checks), wait: `.dpcli/dpcli job wait dp-accept-<ID> <sec>`.

The `scope` row in the table is a deterministic boundary check: files changed in the task branch relative to `base` (`git diff --name-only base...HEAD` + uncommitted) must fall within `scope` and outside `dont_touch` (item — a glob or a file/directory prefix; a path may contain spaces: it is taken whole if the explanation is separated by ` — `, ` - `, ` (` or `: `, or the path is in backticks; without an explanation both the whole line and the first word match). Violation — FAIL with a file list (up to 10). Empty `scope` or a copy not on the task branch — `SKIP`. The module journal (`<plan_dir>/<module>/`, incl. the report), `checks.log_dir` and `gc.ignore_*` are not violations.

Report (`report --template`): `status` (done|partial|blocked|failed), `summary`, `commits[]`, `checks[{name, value, pass}]`, `not_done[]`, `questions[]`, `images[]`, `how_to_check`, `uncertain`, `dp_feedback`, plus the card's `report_extra` keys. An invalid report isn't saved; the error says what's wrong.

Review (`review --template`): `verdict` accept|rework, `summary`, `issues[]` (≤ 7) `{file, line, severity: blocker|major|minor, what, fix}`, `rerun[{name, value, pass}]`. A blocker with accept is an error.

### Plan, status, journal

```
.dpcli/dpcli plan <module|file.md> [<number|heading prefix>] [--contracts] [--depth 3] [--max 150]   # TOC or section
.dpcli/dpcli plan edit <module|file.md> <section> --append "text" | --replace OLD NEW [--all] | --set [FILE|-]  [--contracts] [--commit]
.dpcli/dpcli status [<module>] [--full] [--stale 40] [--since 30m|2h|today]
.dpcli/dpcli digest [--since today|DATE|2h]
.dpcli/dpcli render <module> [--out path|-] [--force]    # md journal <plan_dir>/<module>/journal.md
```

`plan edit --replace` requires exactly one occurrence in the section (`--all` — all); section `*` — the whole file (`--replace` only); `--set` without a file or with `-` reads stdin. `status`: "quiet" — no events and no task branch commits for longer than the threshold (min).

### Search

```
.dpcli/dpcli search <text|regex> [--module M] [--max N]       # across cards, reports, events, decisions of all modules
.dpcli/dpcli search --sem "query" [--max 10] [--module M|--path PREFIX] [--all]
.dpcli/dpcli index [--full]                                    # semantic index
```

Before new work it helps to `search` past modules. Semantic search is optional and off by default (`sem.enabled: false`): without it `search --sem` and `index` report that search is disabled, and `merge` into the main branch doesn't update the index. To enable: `sem.enabled: true` in config, install Ollama and `ollama pull bge-m3`, then `.dpcli/dpcli index`.
When enabled, embeddings come from Ollama (`sem.url`, `sem.model`, default bge-m3; once `ollama pull bge-m3`). The index lives outside git in `sem.cache_dir` and is updated by text hash. `DPCLI_SEM_CPU=1` — CPU only. Corpus — `sem.globs` and dpcli journals. No Ollama or model — an error with a hint.

### Documentation

```
.dpcli/dpcli docs check [path …]                              # frontmatter, summary, live links, size (exit 1 on errors); with paths — only these files (directory — all documents under it)
.dpcli/dpcli docs index                                       # build INDEX.md and registries (docs.registries)
.dpcli/dpcli docs find [--type T] [--status S] [--module M] [--archive] [--long] [text]   # line "path — summary"
.dpcli/dpcli docs section <path>[#section] [<number|heading prefix>] [--depth 3] [--max N]  # TOC or section
.dpcli/dpcli docs show <path.md>                              # frontmatter + TOC
.dpcli/dpcli docs findings [--module M] [text]                # findings from registry/findings.md
.dpcli/dpcli docs init [--dry] [--refresh-contracts]          # frontmatter for files without it (summary: "TODO")
```

Documentation is read piece by piece: `INDEX.md` is the entry point (modules by `area`, one line per module: plan summary, status and date, links to plan, contracts, decisions, summary and journal archive, with other module documents below it; the rest — groups by type, one line per document `- [path](path) — summary [status]`, archive — a single line), `docs find` — one line per document, `docs section` — a document's TOC (without a section) or a section's text with subsections, without frontmatter. Section — a number from the TOC or a heading prefix; if several match — a list of candidates and exit 1 (`plan` resolves sections the same way).

Frontmatter is read as YAML (`related` lists — block `- a` and inline `[a, b]`). `docs check` rules: `summary` is required, one line ≤ `docs.summary_max` (140) chars, `TODO` is an error (`docs init` sets `summary: "TODO"` rather than inventing one from the text); a document larger than `docs.max_kb` (40 KB) is an error with a hint to split into section files or move data out (`docs.max_kb_mode: warn` — warning only; archive and `generated: true` are not checked). `docs find --status closed|superseded` and `--archive` also search `{docs_dir}/archive/`.

Registries: `docs.registries` (default `[research, contracts]`; `decisions` — only if enabled explicitly, otherwise decisions are found via `search`). `registry/findings.md` is written by hand (`docs index` creates a stub): section `## <module>`, a finding — a one-line `- …` item with numbers and a `path#section` link. Allowed `type`/`status`, exclusions and limits — the `docs` config section.

### Long runs and locks

```
.dpcli/dpcli job start <name> <timeout_s> <command…>     # in background; rc is always written, 124 — timeout
.dpcli/dpcli job wait <name> <timeout_s>                  # waits, prints exit code and log tail
.dpcli/dpcli job status [name] [--all]  |  job stop <name>  |  job attach <name>
.dpcli/dpcli job --lock cpu|gpu start <name> <timeout_s> <command…>
.dpcli/dpcli lock cpu|gpu <name> [--timeout SEC] -- <command…>
.dpcli/dpcli lock status
```

Logs — `<jobs.dir>/<name>.{pid,log,rc}`; `rc`: 124 — timeout, 143 — `job stop`, 129 — window closed by the user. The `cpu` lock has N slots (`jobs.cpu_slots` / `DPCLI_CPU_SLOTS`, default half of logical cores), `gpu` — one. A tmux window by default (session `$DPCLI_TMUX_SESSION`, else `jobs.tmux_session`); `--no-tmux` — background only; no tmux — a warning and plain background. The window closes when the job finishes. tmux is disabled inside jobs (`DPCLI_NO_TMUX=1`).

## Module delivery

The journal is working material of the module branch; it doesn't go into the target branch. `deliver <module>`:

1. refuses if there are unaccepted tasks or unanswered questions (`--force` — deliver as is), or if the module or target copy is dirty;
2. commits the journal in the module copy, runs `git merge --squash <module branch>` in the target branch copy (`--into`, default — module base); a conflict only in `INDEX.md`/registries is rebuilt automatically, otherwise — rollback, `sync` first;
3. removes everything from `<plan_dir>/<module>/` except `deliver.keep` (default `decisions.md`, `summary.md`) and writes these files from the journal:
   - `decisions.md` — questions with answers (answer under the question) and decisions by author, with the "why"; dates `YYYY-MM-DD` without time; a user decision without a reason (or with only a source reference like "user answer 2026-10-09") — "approved by developer";
   - `summary.md` — per task: result (report `summary`), status and review verdict, "not done", "uncertain", executor questions;
4. one commit "<module>: <plan title>" with the task list in the body — through hooks (pre-commit checks the whole module); if it fails, changes stay in the index;
   frontmatter of both files gets the module `area` and `archive` (tag with the full journal, if `deliver.archive_tag` is set);
   module plan and contracts (`module` in frontmatter) → `status: closed`, `updated`, `area`; `INDEX.md` and registries are rebuilt (`docs index`) — all in the same commit;
5. a `delivered` event in the module journal and the `deliver.archive_tag` tag (`archive/{module}`; `false` — no tag, then `archive` isn't written to md either) on the module branch — the full journal stays there.

Don't develop the module branch after delivery: a repeated squash doesn't know what was already merged. Follow-up work — a new task or module from the target branch.

`--in-place` — for journals already merged into the current branch with a regular merge: writes the same md (`archive` — the last commit with the journal) and removes the rest in one commit.

`--rerender` — the module is already delivered but the md format changed: the journal is taken from `--from` (tag or commit; default `deliver.archive_tag`) via `git archive`, md files are rewritten, plan and contracts closed, index rebuilt; committing is up to you. Old journal without `area` — `--area`.

## Journal storage

`<plan_dir>/<module>/`:

- `module.json` — module: code, area, branch, copy, plan, contracts;
- `tasks/<ID>.json` — card, `tasks/<ID>.report.json` — executor report, `tasks/<ID>.review.json` — latest review;
- `events.jsonl` — events (append-only): `{t, by, task, ev, commits?, note?}`;
- `decisions.jsonl` — decisions and questions: `{t, by, kind: decision|question, text, why?, id?, answers?}`;
- `.read_<reader>` — inbox read markers (outside git);
- `journal.md` — `render` output;
- `decisions.md`, `summary.md` — `deliver` output (after delivery only these remain in the target branch).

**Journal home** — the module branch working copy, if the module journal is there; otherwise the current copy. So `dpcli` from any copy (main, module, task) reads and writes one journal. The coordinator commits it. `DPCLI_LOCAL=1` — current copy only. dpcli commits nothing itself (except the journal before a merge and `plan edit --commit`).

## Environment variables

| Variable | Purpose |
|---|---|
| `DPCLI_ROLE` | default event author and inbox reader (`main`, `coordinator`, `executor`, …) |
| `DPCLI_LOCAL` | `1` — journal of the current copy only |
| `DPCLI_NO_REEXEC` | `1` — don't re-exec from the main copy |
| `DPCLI_SESSION` | session ID for the line in commit messages |
| `DPCLI_TASK` | current task ID (set during checks) |
| `DPCLI_COPIES` | working copies directory instead of `copies_dir` |
| `DPCLI_CPU_SLOTS` | number of cpu lock slots |
| `DPCLI_NO_TMUX` | `1` — don't open tmux windows |
| `DPCLI_TMUX_SESSION` | tmux session for windows |
| `DPCLI_JOB_DIR` | `job` runs directory instead of `jobs.dir` |
| `DPCLI_SEM_CPU` | `1` — embeddings on CPU only |

`DPCLI_REEXECED` — internal (guards against repeated re-exec).

## Exit codes

- `0` — success;
- `1` — error or a failed check (FAIL);
- `2` — bad arguments.

For `job`/`lock` the exit code is the command's own (124 — timeout).

## Updating dpcli in a project

1. Replace the `.dpcli` directory with the new version (keep or move your own files in `.dpcli/agents`).
2. Run `.dpcli/dpcli init` (or `init --check` to see what changed; `--force` — overwrite hand-edited files).
3. Version — `VERSION` in `.dpcli/lib/dpcli/__init__.py` (`.dpcli/dpcli --version`).

An outdated `.dpcli` in a task working copy re-execs itself from the main copy (`<main worktree>/.dpcli/dpcli`) if `VERSION` there is newer: one line on stderr, arguments and cwd preserved. Disable — `DPCLI_NO_REEXEC=1`. So updating the main copy is enough.
