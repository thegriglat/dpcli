#!/usr/bin/env python3
"""UserPromptSubmit hook: the main session's context (last turn, from transcript_path) over $DPCLI_CONTEXT_MAX
(300k tokens) → one line asking for a fresh session. Each turn re-reads the whole context: a long main session cost
more than all the agents it ran. Fails open."""
import json
import os
import sys

TAIL = 1 << 21  # the last turn is near the end; logs grow to hundreds of MB


def context(path):
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - TAIL))
        lines = f.read().decode(errors="replace").splitlines()
    for ln in reversed(lines):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        u = (r.get("message") or {}).get("usage") if r.get("type") == "assistant" and not r.get("isSidechain") else None
        if u:
            return u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
    return 0


def main():
    try:
        n = context(json.load(sys.stdin)["transcript_path"])
        limit = int(os.environ.get("DPCLI_CONTEXT_MAX") or 300_000)
    except (OSError, ValueError, KeyError, TypeError):
        return 0
    if n > limit:  # stdout of UserPromptSubmit goes into the model's context
        print(f"dpcli: main session context {n // 1000}k > {limit // 1000}k tokens, re-read on every turn — finish "
              f"this step, then tell the user to start a new session (/clear); the state is in the journal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
