"""End-to-end check of the web bridge against fake_pi.py."""
import json
import os
import time

os.environ["PI_CMD"] = "/home/claude/fake_pi.py"
os.environ.setdefault("PI_RESUME", "new")

from fastapi.testclient import TestClient          # noqa: E402
import pi_web_bridge                                # noqa: E402

deltas, kinds, asks = "", [], []

with TestClient(pi_web_bridge.app) as client:
    with client.websocket_connect("/ws") as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot"
        print("SNAPSHOT items:", len(snap["items"]),
              "| cwd:", snap["cwd"])

        ws.send_json({"type": "prompt", "message": "do something danger"})
        rid = None
        deadline = time.time() + 12
        while time.time() < deadline:
            m = ws.receive_json()
            t = m["type"]
            if t == "delta":
                deltas += m["delta"]
            elif t == "item":
                it = m["item"]
                kinds.append(it["kind"])
                label = it.get("text") or it.get("name") or it.get("title") or ""
                print(f"  ITEM  {it['kind']:<10} {str(label)[:52]!r}")
                if it["kind"] == "ask":
                    rid = it["rid"]
                    asks.append(it["options"])
                    print("        options:", it["options"])
                    ws.send_json({"type": "answer", "rid": rid,
                                  "choice": "Allow once"})
                    print("        -> answered: Allow once")
            elif t == "patch":
                print(f"  PATCH id={m['id']}",
                      {k: str(v)[:34] for k, v in m["fields"].items()})
            elif t == "state":
                s = m["state"]
                print(f"  STATE running={s['running']} tool={s['tool']} "
                      f"ctx={s['context']} model={s['model']}")
                if not s["running"] and rid and s["context"]:
                    break

        print("\nSTREAMED TEXT:", repr(deltas))
        print("ITEM KINDS   :", kinds)
        print("DIALOGS      :", asks)

        # a command that is not on the allow list must be refused
        ws.send_json({"type": "rm_rf", "path": "/"})
        for _ in range(6):
            m = ws.receive_json()
            if m["type"] == "rpc" and m["command"] == "rm_rf":
                print("BLOCKED      :", m["data"])
                break

    r = client.get("/api/sessions")
    print("SESSIONS API :", r.status_code, str(r.json())[:90])
    r = client.get("/")
    print("INDEX        :", r.status_code, len(r.content), "bytes")

assert "**that**" in deltas, "streaming lost text"
assert "ask" in kinds, "no permission dialog rendered"
assert "tool" in kinds, "no tool row rendered"
print("\nALL CHECKS PASSED")
