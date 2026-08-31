"""El transcripto se reconstruye desde get_messages al abrir un proyecto."""
import asyncio
import json

import websockets

from harness import Bridge, FakeProject, PORT, report

WS = "ws://127.0.0.1:%d/ws" % PORT


async def main():
    with FakeProject("history") as proj, Bridge():
        async with websockets.connect(WS) as ws:
            snap = json.loads(await ws.recv())
            assert snap["items"] == [], "deberia arrancar vacio"

            await ws.send(json.dumps({"type": "open_project",
                                      "path": proj.path}))
            hist = None
            for _ in range(60):
                m = json.loads(await asyncio.wait_for(ws.recv(), 15))
                if m["type"] == "snapshot" and m["items"]:
                    hist = m["items"]
                    break
            assert hist, "no llego el historial"

            print("  items reconstruidos:", len(hist))
            for it in hist:
                label = (it.get("text") or it.get("name") or "")[:34]
                extra = ""
                if it["kind"] == "tool":
                    extra = " [%s] %s" % (it.get("status"),
                                          (it.get("output") or "")[:22])
                print("  %-10s %-36s%s" % (it["kind"], repr(label), extra))

            kinds = [i["kind"] for i in hist]
            texts = " ".join(str(i.get("text", "")) for i in hist)
            tools = [i for i in hist if i["kind"] == "tool"]
            done = [t for t in tools if t.get("callId") == "h1"]
            orphan = [t for t in tools if t.get("status") == "error"]
            ids = [i["id"] for i in hist]

            return report([
                ("el bloque thinking no se cuela",
                 "esto no debe salir" not in texts),
                ("orden de los turnos",
                 kinds[:4] == ["user", "assistant", "tool", "assistant"]),
                ("mensaje de usuario en texto plano",
                 "primer encargo" in texts),
                ("mensaje de usuario en bloques", "segundo encargo" in texts),
                ("segunda respuesta", "**ya esta**" in texts),
                ("la llamada se cierra con su resultado",
                 bool(done) and done[0]["status"] == "done"
                 and "com.android" in done[0]["output"]),
                ("un resultado sin llamada sale igual",
                 bool(orphan) and orphan[0]["name"] == "bash"),
                ("la nota del proyecto cierra", kinds[-1] == "note"),
                ("sin ids repetidos", len(ids) == len(set(ids))),
            ])


raise SystemExit(asyncio.run(main()))
