#!/usr/bin/env python3
"""SubagentStop hook: a dpcli agent's final reply must be one protocol line (workflow, "Message protocol") — the
parent pays for every word of it. By the agent's dpcli_role: executor `<ID> reported|blocked: …|contract: …`,
reviewer `<ID> review accept|rework <n>`, coordinator `<m>: …` / `<m> done`; a one-line question passes too.
A wrong reply is sent back once (exit 2, the hint goes to the agent); on the retry (stop_hook_active) it passes.
Agents without a dpcli role and any error — pass (fails open)."""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

ID = r"[A-Z]{2,4}-[A-Z]?\d+[a-z]?"
FORMATS = {
    "executor": (rf"{ID} (reported|blocked: .+|contract: .+)", "<ID> reported | <ID> blocked: <reason ≤15 words> | "
                 "<ID> contract: <what to change>"),
    "reviewer": (rf"{ID} review (accept|rework \d+)", "<ID> review accept | <ID> review rework <n issues>"),
    "coordinator": (r"[\w.-]+( done|: .+)", "<m>: <n> accepted, <n> in progress; gate Q<n> | <m>: wave <n> done | <m> done"),
}


def role_of(agent_type, cwd):
    if cwd:
        os.chdir(cwd)
    from dpcli import agents
    a = agents.load_agents().get(agent_type) or {}
    return a.get("role")


def verdict(data):
    if data.get("stop_hook_active"):
        return None
    role = role_of(data.get("agent_type") or "", data.get("cwd"))
    if role not in FORMATS:
        return None
    msg = (data.get("last_assistant_message") or "").strip().strip("`").strip()
    if not msg:
        return None  # nothing to judge (a reply sent through a handback tool is not in last_assistant_message)
    rx, human = FORMATS[role]
    if "\n" not in msg and (re.fullmatch(rx, msg) or (msg.endswith("?") and len(msg) <= 300)):
        return None
    return (f"dpcli: your reply goes to the parent agent and must be one protocol line: {human}. Details belong in "
            f"the journal (report / review / event note), not in the reply. Answer again with that line only.")


def main():
    try:
        msg = verdict(json.load(sys.stdin))
    except Exception:  # noqa: BLE001 — a guard must never break the session
        return 0
    if msg:
        print(msg, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
