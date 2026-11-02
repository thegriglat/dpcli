# dpcli

**Run a team of Claude Code agents on a real codebase — with a journal, acceptance checks, isolated worktrees, and a process that improves itself.**

[![tests](https://github.com/zolotarev/dpcli/actions/workflows/test.yml/badge.svg)](https://github.com/zolotarev/dpcli/actions/workflows/test.yml)
![python](https://img.shields.io/badge/python-%E2%89%A53.10-blue)
![dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

One main session plans. A coordinator per module writes contracts and task cards. Executors each work on one task in their own git worktree. A reviewer with a fresh context checks risky work. dpcli is the single CLI they all use to hand work over — so agents exchange **IDs and commands, not walls of text**, and every decision, report and verdict lands in an append-only journal in git.

```
$ .dpcli/dpcli task brief BL-1          # the whole message a coordinator sends an executor
BL-1 dp-engineer: Invoice totals
Copy: ~/worktrees/app/billing-BL-1  branch: billing/BL-1 (from feature/billing)
Do: .dpcli/dpcli task show BL-1  · plan: .dpcli/dpcli plan billing <section>
Scope: only src/billing.py
Done when: .dpcli/dpcli accept BL-1 --dry → PASS; report: build/dpcli/BL-1/report.json → .dpcli/dpcli report BL-1
Reply: one line «BL-1 reported» | «BL-1 blocked: <reason ≤15 words>» | «BL-1 contract: <what to change>»

$ .dpcli/dpcli accept BL-1 --dry
PASS unit  exit 0
PASS scope 1 file(s) within bounds
BL-1: 1/1 in .

$ .dpcli/dpcli status
billing: created 1 | event 0m ago | feature/billing 6509356 0m @ .
  BL-1 created 0m engineer billing/BL-1 1900700 0m
  ? Q1 awaits decision (0m): Round tax per line or per invoice?
```

## Why

Multi-agent coding falls apart in predictable ways: agents retell each other's context and burn tokens, edit files outside their task, "pass" by weakening tests, overwrite each other's work, and repeat the same mistakes forever. dpcli turns these into mechanics:

| Problem | dpcli |
|---|---|
| Context bloat between agents | A message protocol of one-line IDs; details are read from the journal on demand |
| Agents wander outside the task | Task cards with `scope` / `dont_touch`; `accept` fails on out-of-scope changes |
| "Done" that isn't | Executable acceptance checks with thresholds; risk-based fresh-context review |
| Agents trample each other | One git worktree and branch per task; locks for CPU/GPU-heavy runs |
| Same frictions every week | Agents log frictions as they work; dpcli clusters them, fixes ship as PRs to this repo, every project gets them on update |

> **Status:** released — the core (journal, cards, acceptance, worktrees, delivery), the installer, the friction ledger (`feedback`, `stats`, `contribute`), auto-update and the hub CI (tests, budgets, AI review and merge, nightly simplification). See [ROADMAP.md](ROADMAP.md).

## Quick start

In the root of an existing git project:

```sh
curl -fsSL https://raw.githubusercontent.com/zolotarev/dpcli/main/install.sh | bash
# options: --lang ru --commit-lang en --tools (install rg, fd, jq, ast-grep) --yes
```

The installer adds dpcli as the git submodule `.dpcli`, asks which language agents should write in (and, separately, commit messages), creates `dpcli.yml`, and runs `.dpcli/dpcli init` — agents, skills and the process description land in `.claude/`. Commit the result, then in Claude Code:

```
> Read .claude/dpcli-workflow.md and plan module "billing" from docs/plan/billing.md
```

Requirements: git, Python ≥ 3.10. No other dependencies.

## How it works

```mermaid
flowchart LR
  U((user)) --- M[main session]
  M -- "module new" --> C[coordinator]
  C -- "task brief" --> E1[executor<br/>own worktree]
  C -- "task brief" --> E2[executor<br/>own worktree]
  E1 -- "ID reported" --> C
  C -- "accept → review" --> R[reviewer<br/>fresh context]
  C -- "gate Qn" --> M
  E1 & E2 & C & R --> J[(journal in git)]
```

- **Journal** — `docs/plan/<module>/`: cards, reports, reviews, `events.jsonl`, `decisions.jsonl`. Append-only, readable by humans (`render`) and agents (`status`, `log`, `inbox`, `search`).
- **Cards and acceptance** — `task new` with scope, checks (`exit=0`, regex, numeric thresholds, test filters), contracts; `accept` runs them and records PASS/FAIL.
- **Branches and copies** — module and task branches, one worktree per task, `merge`, `deliver` (squash a finished module into its base), `gc`.
- **Long runs** — `job start/wait` and shared `lock cpu|gpu` so agents don't poll or collide.

Full reference: [docs/guide.md](docs/guide.md).

## A self-improving network

Every project using dpcli is a node; this repository is the hub.

```mermaid
flowchart LR
  A[project A] -- PR / issue 'feedback' --> H[(dpcli hub)]
  B[project B] -- PR / issue 'feedback' --> H
  H -- CI: tests · budgets · AI review --> V{verdict}
  V -- accept: merge + tag --> UP[dpcli update in every project]
  V -- rework / reject + arguments --> A
  N[nightly: measure & shrink] --> H
```

1. Agents log frictions as one line while they work.
2. `dpcli feedback` clusters them; project-specific fixes go into the project's `.dpcli-local/`, dpcli-level fixes become a pull request here via `dpcli contribute` (or a `+1` on an existing one).
3. CI runs the tests and size budgets, an AI reviewer accepts, asks for rework, or rejects with arguments.
4. On session start `dpcli update` pulls the new version into every project — and tells each node what happened to its own PRs.
5. A nightly job measures how heavy dpcli got and opens a PR that makes it smaller.

See [ROADMAP.md](ROADMAP.md) for where this stands and [SECURITY.md](SECURITY.md) for the trust model.

## Contributing

The easiest way is to use dpcli: frictions become PRs on their own. Manual PRs are welcome too — see [CONTRIBUTING.md](CONTRIBUTING.md). Tests: `python3 -m unittest discover -s tests`.

## License

[MIT](LICENSE)
