# dpcli — working in this repository

A portable process tool for projects run by Claude Code agents. User docs — [README.md](README.md), plan — [ROADMAP.md](ROADMAP.md), contributing — [CONTRIBUTING.md](CONTRIBUTING.md). Includes the changes of the fork zolotarev/dpcli up to its v36, without its hub (auto-update, `contribute`, AI review/merge, nightly).

## Layout
- The repository root is the distribution; in a project it is copied to the folder `.dpcli` by `install.sh` (check it that way: `cd <project> && .dpcli/dpcli …`). Entry point `dpcli`, package `lib/dpcli` (commands in `commands/*.py`, each exports `register(sp)`), `agents/`, `hooks/`, `skills/`, `templates/`, `dpcli.example.yml`, `install.sh`.
- `tests/` — unittest; shared fixture `tests/helpers.py` (`Project` — a temporary git project with the distribution copied to `.dpcli`).
- `.github/` — CI (tests, budgets), issue/PR templates. `tools/metrics.py` — size of agent prompts vs `tools/budgets.json`.

## Rules
- Python ≥ 3.10 standard library and git only; no new dependencies (Ollama for `search --sem` is optional).
- Any change to the distribution → bump `VERSION` in `lib/dpcli/__init__.py` (stale copies re-exec the main one by it, `reexec.py`) and add a `CHANGELOG.md` line.
- Fixing a friction: first a test that reproduces it, then the change.
- Before committing: `python3 -m unittest discover -s tests` (~1 min), all green.
- Requirements come from agent feedback (`dp_feedback`, `harness:` notes) in projects that use dpcli; no data — no feature.
- Output is for agents: terse, one fact per line, the next command as a hint; never truncate silently.
- Journal compatibility: `events.jsonl` / `decisions.jsonl` are append-only; new fields are optional; old (incl. Russian) journals keep reading.
- English everywhere: code, comments, CLI output, agents, templates, docs, commits. Text dpcli writes into a project's files goes through `lang_text(en, ru)`, commit messages through `lang_commit(en, ru)` (`util.py`, config `language.text` / `language.commits`).
- Project vs dpcli: project-specific rules, agent additions and the friction ledger live in the project's `.dpcli-local/`, never here. Improvements to dpcli itself come here as ordinary commits/PRs made by a human.
- Public repository: no project data (names, paths, quotes) — only anonymized conclusions.
- Lightness is a feature: agent prompts and templates are paid on every agent run; `tools/budgets.json` caps them. Deleting beats adding.
