"""dpcli — journal, task cards and module acceptance (Python >= 3.10 standard library only).

Storage: <plan_dir>/<module>/ — module.json, tasks/<ID>.json (card), tasks/<ID>.report.json
(executor report), tasks/<ID>.review.json (review), events.jsonl and decisions.jsonl (append-only).
The module journal lives in the working copy of the module branch (module_branch) if it exists (visible
from any copy), otherwise in the current copy. Exit codes: 0 ok, 1 error/check failed, 2 arguments.
"""

VERSION = 3  # bump on every change: older copies re-exec from the main one (reexec.maybe_reexec)
