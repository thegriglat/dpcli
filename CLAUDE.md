# dpcli — working in this repository

A portable process tool for projects run by Claude Code agents. User docs — [README.md](README.md), plan — [ROADMAP.md](ROADMAP.md), contribution flow — [CONTRIBUTING.md](CONTRIBUTING.md).

## Layout
- The repository root is the distribution; in a project it is the submodule `.dpcli` (check it that way: `cd <project> && .dpcli/dpcli …`). Entry point `dpcli`, package `lib/dpcli` (commands in `commands/*.py`, each exports `register(sp)`), `agents/`, `skills/`, `templates/`, `dpcli.example.yml`.
- `tests/` — unittest; shared fixture `tests/helpers.py` (`Project` — a temporary git project with the distribution copied to `.dpcli`).
- `.github/` — CI of the central repository (tests, budgets, AI review and merge, nightly simplification), issue/PR templates.

## Rules
- Python ≥ 3.10 standard library and git only; no new dependencies (Ollama for `search --sem` is optional).
- Any change to the distribution → bump `VERSION` in `lib/dpcli/__init__.py` (stale copies re-exec the main one by it, `reexec.py`) and add a `CHANGELOG.md` line.
- Fixing a friction: first a test that reproduces it, then the change.
- Before committing: `python3 -m unittest discover -s tests` (~1 min), all green.
- Requirements come from agent feedback (`dp_feedback`, `harness:` notes) in projects that use dpcli; no data — no feature.
- Output is for agents: terse, one fact per line, the next command as a hint; never truncate silently.
- Journal compatibility: `events.jsonl` / `decisions.jsonl` are append-only; new fields are optional; old (incl. Russian) journals keep reading.
- English everywhere: code, comments, CLI output, agents, templates, docs, commits. Text dpcli writes into a project's files goes through `lang_text(en, ru)`, commit messages through `lang_commit(en, ru)` (`util.py`, config `language.text` / `language.commits`).
- Project vs dpcli: project-specific rules, agent additions and the friction ledger live in the project's `.dpcli-local/`, never here. Improvements to dpcli itself reach `main` only via PR (`dpcli contribute`), label `feedback`.
- Public repository: no project data (names, paths, quotes) — only anonymized conclusions.
- Lightness is a feature: agent prompts and templates are paid on every agent run; `tools/budgets.json` caps them, a nightly job tries to shrink the code. Deleting beats adding.
