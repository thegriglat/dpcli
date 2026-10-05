"""agents: реестр агентов dpcli — имя, роль, review, источник, модель."""
from .. import agents


def cmd_agents(a):
    reg = agents.load_agents()
    rows = [(n, x.get("role") or "-", "да" if x.get("review") else "нет", x.get("source", "-"), str(x.get("model") or "-"))
            for n, x in sorted(reg.items(), key=lambda kv: (agents.ROLES.index(kv[1]["role"])
                                                           if kv[1].get("role") in agents.ROLES else 9, kv[0]))]
    head = ("имя", "роль", "review", "источник", "модель")
    w = [max(len(r[i]) for r in rows + [head]) for i in range(5)]
    for r in [head] + rows:
        print("  ".join(c.ljust(w[i]) for i, c in enumerate(r)).rstrip())
    if not any(x.get("role") == "executor" for x in reg.values()):
        print("нет исполнителей (dpcli_role: executor или roles в конфиге)")


def register(sp):
    q = sp.add_parser("agents", help="реестр агентов: роль, review, источник (dpcli|project|config), модель")
    q.set_defaults(func=cmd_agents)
