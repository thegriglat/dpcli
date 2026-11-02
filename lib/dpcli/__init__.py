"""dpcli: journal, task cards and module acceptance (Python ≥ 3.10 standard library only).

Storage: <plan_dir>/<module>/ has module.json, tasks/<ID>.json (card), tasks/<ID>.report.json
(executor report), tasks/<ID>.review.json (review), events.jsonl and decisions.jsonl (append-only).
The module journal lives in the module-branch copy (module_branch) if there is one (visible from any copy),
else in the current copy. Exit codes: 0 ok, 1 error/check failed, 2 arguments.
"""

VERSION = 37  # bump on every change: older copies re-exec from the main copy (reexec.maybe_reexec)
