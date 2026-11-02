"""agents: dpcli agent registry: name, role, review, source, model."""
from .. import agents


def cmd_agents(a):
    reg = agents.load_agents()
    rows = [(n, x.get("role") or "-", "yes" if x.get("review") else "no", x.get("source", "-"), str(x.get("model") or "-"))
            for n, x in sorted(reg.items(), key=lambda kv: (agents.ROLES.index(kv[1]["role"])
                                                           if kv[1].get("role") in agents.ROLES else 9, kv[0]))]
    head = ("name", "role", "review", "source", "model")
    w = [max(len(r[i]) for r in rows + [head]) for i in range(5)]
    for r in [head] + rows:
        print("  ".join(c.ljust(w[i]) for i, c in enumerate(r)).rstrip())
    if not any(x.get("role") == "executor" for x in reg.values()):
        print("no executors (dpcli_role: executor or roles in config)")


def register(sp):
    q = sp.add_parser("agents", help="agent registry: role, review, source (dpcli|project|config), model")
    q.set_defaults(func=cmd_agents)
