# dpcli

[![tests](https://github.com/thegriglat/dpcli/actions/workflows/tests.yml/badge.svg)](https://github.com/thegriglat/dpcli/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![deps](https://img.shields.io/badge/dependencies-none-brightgreen)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**A portable process tool for multi-agent [Claude Code](https://docs.claude.com/en/docs/claude-code) projects.**

Multi-agent work burns context: coordinators retell plans to executors, executors retell results back, reviewers re-read everything. dpcli replaces retelling with a journal and short structured messages — agents pass an ID and a command, details are read on demand.

- **Module journal** — task cards, reports, events, decisions and questions to the user, stored as plain JSON/JSONL next to the plan.
- **Task cards with explicit boundaries** — `goal`, `scope`, `dont_touch` and acceptance checks; a card without them is not issued.
- **Deterministic acceptance** — `accept` runs the card's checks (exit code, regex, numeric thresholds, project tests) and verifies the diff stayed inside `scope`.
- **Review** — structured reviewer verdicts (`accept` / `rework`) attached to the task.
- **Branches and working copies** — a git worktree per module and per task, with git-crypt, hooks and `node_modules` set up; `sync`, `merge`, `deliver` (squash + journal → `decisions.md`, `summary.md`) and `gc`.
- **Docs registry** — frontmatter checks, index, section lookup; optional semantic search via Ollama.
- **Non-destructive setup** — `init` renders agents, skills and a workflow description into `.claude/` and never overwrites the project's own files.

## How it works

```
 user ⇄ main session ──module new──▶ module coordinator ──task brief──▶ executor(s)
            ▲                          │      ▲                            │
            │  status / digest         │      └──── <ID> reported ─────────┘
            │                          │ accept (checks + scope) → review (fresh reviewer)
            └──── decide / answer ─────┘ merge → sync → deliver
```

| From → to | Message |
|---|---|
| coordinator → executor | output of `dpcli task brief <ID>`, as is |
| executor → coordinator | `<ID> reported` \| `<ID> blocked: <reason>` |
| reviewer → coordinator | `<ID> review accept` \| `<ID> review rework <n>` |
| coordinator → main | `<m>: <n> accepted, <n> in progress; gate Q<n>` |

## Requirements

- Python ≥ 3.10, standard library only (PyYAML is used if present);
- git;
- optional: tmux (background jobs), Ollama with `bge-m3` for semantic search (off by default).

## Installation

```sh
cp -r .dpcli /path/to/project/      # root of a git project
cd /path/to/project
.dpcli/dpcli init
```

`init` is idempotent: it creates `dpcli.yml`, renders agents and skills into `.claude/`, adds a block to `CLAUDE.md` and a permission to `.claude/settings.json`. Commit `.dpcli/` and `.claude/` afterwards.

## Quick example

```sh
.dpcli/dpcli module new payments --code PY          # module branch + working copy + journal
.dpcli/dpcli task new payments --type dp-engineer --title "Amount rounding" \
  --goal "Amounts are rounded to cents" --scope src/money.py --test rounding \
  --check no_todo "grep -c TODO src/money.py" "re:^0$"
.dpcli/dpcli task brief PY-1                         # message for the executor
.dpcli/dpcli report PY-1 < r.json                    # executor's report
.dpcli/dpcli accept PY-1                             # PASS / FAIL
.dpcli/dpcli status                                  # tasks, branches, open questions
.dpcli/dpcli deliver payments                        # squash into the module base
```

Full reference — config, commands, card format, workflow: [.dpcli/README.md](.dpcli/README.md).

## Repository layout

| Path | Contents |
|---|---|
| `.dpcli/` | the distribution — everything copied into a project |
| `.dpcli/dpcli`, `.dpcli/lib/dpcli/` | entry point and package |
| `.dpcli/agents/`, `.dpcli/skills/`, `.dpcli/templates/` | agent definitions, skills, workflow and `CLAUDE.md` templates |
| `.dpcli/dpcli.example.yml` | annotated config |
| `tests/` | unittest suite |

## Development

```sh
python3 -m unittest discover -s tests
```

Bump `VERSION` in `.dpcli/lib/dpcli/__init__.py` on every change: older copies in worktrees re-exec the newer one from the main copy.

## License

[MIT](LICENSE)
