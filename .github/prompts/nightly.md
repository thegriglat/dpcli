# Nightly: make dpcli smaller

Contributions keep arriving; your job tonight is the opposite force — keep dpcli light. Make **at most one** pull request that reduces size **without changing behaviour**.

## Find one improvement (read `metrics.json`, then the code)
In order of value:
1. Agent prompts and templates (`agents/`, `skills/`, `templates/`) — every token is paid on every agent run: remove repetition across files, wordiness, rules nobody needs; keep every instruction that changes behaviour.
2. Dead code, duplicated logic, needless abstraction in `lib/dpcli/` (see `duplicate_windows`, the largest files).
3. A risky spot (`risky` counts): a force/destructive path that can be made safer without losing function.

## Rules
- Behaviour stays the same: all tests must pass; don't edit tests except removing tests of code you deleted as dead.
- The diff must have a negative balance of lines (and of prompt tokens if you touch prompts).
- No new features, no renames for taste, no reformatting.
- If nothing worthwhile (< ~20 lines or < ~100 tokens), stop without a PR.

## Deliver
1. `git switch -c nightly/<run id>`; make the change; `python3 -m unittest discover -s tests`; `python3 tools/metrics.py --write-budgets` (budgets go down to the new values); bump `VERSION` in `lib/dpcli/__init__.py`; add a `## <N>` CHANGELOG section with one line.
2. Commit, `git push -u origin HEAD`, `gh label create nightly-simplify --color 5319E7` (ignore "exists"), then `gh pr create --base main --label nightly-simplify --title "nightly: <what got smaller>" --body "<before → after numbers from metrics; what was removed and why behaviour is unchanged>"`.
