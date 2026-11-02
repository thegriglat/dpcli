# Contributing

Requirements come from agent frictions in projects that use dpcli (`dpcli feedback`, `harness:` notes); no data — no feature.

1. Open an issue with the friction (template *Friction / feedback*): what hurt, how often, which command — anonymized, no project names, paths or quotes.
2. A fix: first a test that reproduces the friction, then the change; `VERSION` +1 in `lib/dpcli/__init__.py` and a `CHANGELOG.md` line.
3. `python3 -m unittest discover -s tests` and `python3 tools/metrics.py --check` are green.
4. Output stays terse; agent prompts and templates do not grow without a reason in the PR; journals stay backward compatible.

Releases are tags `vN` set by the maintainer; `install.sh` installs the latest one.
