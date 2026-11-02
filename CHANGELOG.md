# Changelog

## 36
- `gc --remove` removes copies with a submodule (git refused without `--force`) and copies whose status shows changes but content equals HEAD (a hook restored the files); a change, a stash or a commit on no remote inside a submodule still blocks removal, and so does a failed submodule check.

## 35
- `gc` also removes branches squash-merged into the main branch, and branches merged into them.

## 34
- `contribute` makes the `improve/F-n-*` branch and the commit from uncommitted edits in `.dpcli`: agents may run dpcli but not git there, so a friction stopped on a permission.
- `update` keeps `.dpcli` on branch `main` at the release (not a detached tag next to a lagging local `main`), prunes deleted hub branches, and drops the local `improve/F-n-*` branch of a merged PR (one left checked out blocked every later update).
- `update` lists contributions written to disk because `gh` was not logged in, until they are sent.

## 33
- `accept` scope check ignores submodule pointers: a copy's `.dpcli` checkout drifts from the recorded commit and gave a false `outside scope: .dpcli`.

## 32
- `deliver` keeps the module's frictions (`harness:` notes, `dp_feedback`, review `harness`): before it drops the journal they go to the ledger as `item` records, and `feedback`/`stats` read them from there — they used to vanish with the journal.
- `decisions.md` / `summary.md` link the module plan in `related` only if the plan file exists (`docs check` reported a missing file for modules without one).

## 31
- `merge --into <branch>` when no copy has the branch open (e.g. the main copy cannot switch to `main`: a vendored `.dpcli` there, the submodule on the feature branch): a fast-forward moves the ref without a checkout (`update-ref` with the old value); a diverged target is refused with the hint to merge it into the source first.

## 30
- `update` moves `.dpcli` to the release tag when it already has the release's VERSION but sits on another commit (an own PR squash-merged, the branch commit still checked out); it used to report "up to date" and commit the pointer at the branch commit.

## 29
- CLAUDE.md block: after a merge — `gc --remove` (merged copies and branches); sessions left merged branches behind.

## 28
- Hook `UserPromptSubmit` (`hooks/context_guard.py`, installed by `init`): when the main session's last turn is over `$DPCLI_CONTEXT_MAX` (300k) tokens, one line asks to finish the step and start a new session — a long main session re-reads its context on every turn and cost more than all the agents it ran.
- `stats --tokens` adds the main sessions' context tokens (all modules, `--since` applies).
- `contribute F-n` requires the branch `improve/F-n-…`: it pushes the current branch, and from another cluster's branch the PR carried that cluster's commits.
- CLAUDE.md block: one `dpcli` command per Bash call — a chained one misses the permission rule and was refused.

## 27
- `module new` tells dpcli branches by the journal (module branches, task card branches), not by the `module_branch` / `task_branch` templates: a feature branch like `feature/x` or `a/b` is a valid base again.
- `accept` estimates check durations from the task's journal (`durs`) when this copy has no `results.json` — `accept --here` in the module copy goes to the background like in the task copy.

## 26
- `feedback`: a report's `dp_feedback` given as a list is read as one friction per entry (was a TypeError for the whole ledger).

## 25
- `accept`: checks run with stdin from `/dev/null` — a formatter called without files (`prettier --check`) waited on the agent's open stdin until the check timeout.

## 24
- `stats --tokens`: context tokens spent by executors, reviewers and coordinators per module, and per task, read from Claude Code's subagent logs (an agent is attributed by its first message — the dpcli brief). Lets a process change be checked by numbers.

## 23
- `update` re-renders `.claude/` when the version is current but the generated files are not (`init --check`) — seen when the submodule was moved by hand; if they stay stale after `init` (edited by hand), it says so instead of re-rendering on every run.
- `task new|set` rejects duplicate check names: results and logs are kept per name since v21.

## 22
- A `PreToolUse` hook (installed by `init`, delivered by `update`) refuses editing project files through Bash and points the agent to Edit/Write; programs, reads and temporary files pass. In the first project agents made ≈1200 such edits and no Edit calls; the v20 rule alone was not expected to change that.

## 21
- Reviewing work that lives in the main copy (a `--no-copy` card): `task brief` names the copy and branch where the work is instead of a copy that does not exist; `accept --here` checks the uncommitted changes against the scope instead of skipping it.
- Check logs are named by the check (`<log_dir>/<ID>/<check>.log`): with `--only` or re-created checks, stale logs of the same check stayed next to fresh ones under other numbers.
- `feedback --module/--since` lists only clusters that have frictions in that slice.

## 20
- Process rule: files are read and edited with the Read, Edit and Write tools, Bash runs programs (`rg`, `fd`, `jq`, `ast-grep`) — executors had edited files almost only through `python3 -`/`sed -i`/`cat >` heredocs.
- `install.sh --tools`: quiet non-interactive apt; a hint when `~/.local/bin` is not on PATH.

## 19
- `accept` warns when `git stash` is not empty: the stash is shared by all worktrees, and a pop in one copy took another task's changes (6 reports; the rule alone did not stop it).

## 18
- `task show` prints the "General rules" section of the process description; executor and reviewer prompts point there instead of the whole file (≈460 instead of ≈3300 tokens per task).
- A review stores the commit it looked at; after a rework `task brief --review` points the fresh reviewer to the previous issues and the diff since that commit only.
- One coordinator per wave: it reports `<m>: wave <n> done` and stops; the main session starts a fresh one (a growing context is paid on every turn).

## 17
- `accept` goes to the background by itself when its checks took longer than `checks.bg_after` (100 s) last time, and prints the wait command; `--fg` stays (21 reports: long foreground runs hit the agent's tool timeout).
- `task new|set --check-timeout NAME SEC`: a check's timeout in the card.
- `lock` runs in the foreground with its output by default; `--tmux` for a window (12 reports: output lost in a tmux job).
- Job names are per copy (`<copy>~<name>`): copies starting the same name no longer read each other's job (3 reports); jobs started before the update are still found by their old name.

## 16
- Scope checks no longer fail on files the card itself requires (25 reports): exclusions are `!pattern` entries in `scope`/`dont_touch`; prose like "src/api/ except a.py" is rejected at `task new`/`task set`; a scope path or glob directory inside `dont_touch` is rejected there too; files brought into the task branch by merges no longer count — the net diff restricted to the branch's own commits (accepted limitation: edits made while resolving a merge are not checked — `accept` says so when the branch has merges); `task new` lists test files that mention scope files so they can be added up front.

## 15
- `plan <m> <section>`: a section of several words needs no quotes; `5. Tasks / DS-0` and `4. Tasks (PF-5)` find the section by their most specific part; a card's `plan_ref` is checked at `task new` / `task set` (19 reports: "section from the card not found").
- `report <ID>` reads the per-task file `<log_dir>/<ID>/report.json` by default (brief and `task show` name it) and rejects a report whose `id` is another task's (13 reports: parallel agents overwrote a shared `/tmp/r.json`); a report without `id` is still accepted (old reports); explicit input (`FILE`, `< FILE`, `-` for a pipe) beats a stale per-task file; a pipe now needs `-` (an idle pipe in agent shells used to block); a report without `id` read from a file gets a warning.

## 14
- `install.sh`: no longer fails with `mv: cannot stat '.dpcli'` when `.dpcli` is recorded as a submodule without a `.gitmodules` entry (now registered and checked out) or when a vendored copy is tracked but deleted from disk (restored from the index first).

## 13
- Process description (`workflow.md`) trimmed by ~110 tokens more: duplicated and decorative phrases removed, no rule changed.

## 12
- Process description (`workflow.md`) trimmed by ~100 tokens: repeated and decorative phrases removed, no rule changed.

## 11
- `update` also commits the re-rendered process description (`workflow`, `.claude/dpcli-workflow.md` by default); it was left uncommitted when a release changed it.

## 10
- `task show` prints addenda in full (they were cut at 300 characters; executors missed instructions added after the brief); older than the last five — counted, shown with `--full`.

## 9
- `gc`: one `git status --ignored` per copy per run instead of one per (branch × copy) — 25 merged copies: 6.6 s → 0.9 s. Removed copies no longer block neighbours.
- Process rule: fast tools for agents (`rg`, `fd`, `jq`, `ast-grep`, Read with offset instead of `cat`/`sed -n`, scripts instead of long heredocs); `install.sh --tools` installs them.
- Measured on a real project and left as is (≤ 0.6 s): `status`, `status --since`, `search`, `docs find`, `docs check`, `feedback`.

## 8
- `install.sh`: installs or updates dpcli in an existing project (`curl … | bash`): submodule at the latest release, `language` (asked or `--lang` / `--commit-lang`), `worktree.setup`, `init`; migrates a vendored copy (own agents → `.dpcli-local/agents/`); `--tools` installs `rg`, `fd`, `jq`, `ast-grep`. Idempotent, never commits.

## 7
- `dpcli update [--auto] [--check] [--pin vN|--unpin] [--prs-only]`: moves the `.dpcli` submodule to the latest release tag, re-runs `init` with the project layer, commits the pointer and generated files, prints the new CHANGELOG lines; skips when `.dpcli` is dirty, on `improve/*`, has local commits, or offline.
- Checks own PRs/issues at the hub: merged → fixed; rework/rejected → reviewer arguments into the ledger.
- `init` adds the `SessionStart` hook `update --auto` (once a day).

## 6
- `dpcli feedback`: friction ledger from `dp_feedback`, `harness:` notes and review `harness`; dedup, clusters by topic, `new --match --scope project|dpcli`, `fix`, `wontfix`, `reopen`, `⚠N after fix` when a fixed friction comes back. Ledger in `.dpcli-local/feedback.jsonl`.
- `dpcli stats`: tasks, created→accepted, rework rounds, frictions per module; check durations (median/max) — `accept` now stores them.
- `dpcli contribute F-n`: a dpcli-scope fix as a PR to the hub from origin or a fork, a +1 on a similar open PR/issue, an issue without commits, or a patch when `gh` is unavailable. Anonymized bodies.
- `harness-retro` rebuilt on top of these; review template gets a `harness` field.

## 5
- Project layer `.dpcli-local/` (`local_dir`): `agents/<name>.append.md`, own agents and skills, project rules in the workflow and CLAUDE.md block; rendered by `init` on top of the distribution, survives updates.

## 4
- Everything in English: code, CLI output, agents, templates, docs. `language.text` / `language.commits` in the config choose the language agents write in and the language of commit messages.
- Repository presentation: CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, issue and PR templates.

## 3
- Layout: the repository root is the distribution; install into a project as the submodule `.dpcli` (`worktree.setup` initializes it in new copies).
- Agent models: coordinator and reviewer on sonnet (opus for the hardest reviews — at launch).
- `harness-retro` skill: process friction review and token cost measurement (`cost.py`); process changes only with the user's approval.
- Process: one session per phase/module, the main session does not poll on a timer, frictions logged as one-line `harness: …`.

## 2
- `deliver`, `area`, module base, worktree copy preparation (`worktree`), `protect_main`, `docs findings`, copies under `~/worktrees`.
