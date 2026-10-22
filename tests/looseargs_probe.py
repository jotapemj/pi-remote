"""Historial con `arguments` en string JSON: el puente no debe romperse.

Caso real (bridge.log): un `edit` grabado con `arguments` y cada `edits` como
string JSON. El puente hacia `args.get("edits")` y reventaba en `load_history`
('str' object has no attribute 'get'): el transcripto se pintaba a medias y el
resto de mensajes del turno desaparecian. `PI_FAKE_LOOSE_ARGS=1` mete ese caso
en el payload de `get_messages` del fake, y nada mas.
"""
import asyncio
import json

import websockets

from harness import Bridge, FakeProject, PORT, report, WS_URL


async def main():
    with FakeProject("looseargs") as proj, \
            Bridge(extra={"PI_FAKE_LOOSE_ARGS": "1"}):
        async with websockets.connect(WS_URL) as ws:
            json.loads(await ws.recv())
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
            for it in hist[-6:]:
                print("  %-10s %s" % (it["kind"],
                      repr((it.get("text") or it.get("name") or "")[:40])))

            texts = " ".join(str(i.get("text", "")) for i in hist)
            tools = [i for i in hist if i["kind"] == "tool"]
            ed = [t for t in tools if t.get("callId") == "l1"]
            asks = [i for i in hist if i["kind"] == "ask"]
            kinds = [i["kind"] for i in hist]
            ids = [i["id"] for i in hist]
            loose = [t for t in tools if t.get("args") is not None
                     and not isinstance(t.get("args"), dict)]
            q = asks[0]["quiz"][0]["question"] if (
                asks and asks[0].get("quiz")) else ""

            return report([
                # el corte es el sintoma medible: lo grabado despues del
                # case suelto tiene que estar pintado
                ("el historial sigue despues del case suelto",
                 "sigue el hilo despues de lo suelto" in texts),
                ("la edicion en string trae su recuento",
                 bool(ed) and ed[0].get("added") == 3
                 and ed[0].get("removed") == 2),
                ("y sus lineas de diff",
                 bool(ed) and bool(ed[0].get("lines"))),
                ("la edicion se cierra con su resultado",
                 bool(ed) and ed[0].get("status") == "done"),
                ("los args de cada fila llegan como dict (o no llegan)",
                 bool(tools) and not loose),
                # el otro agujero: ask_user en string no crash, desaparecia
                ("la tarjeta de ask_user del historial sale con su pregunta",
                 bool(asks) and "Que rama uso" in q),
                ("y aparece contestada",
                 bool(asks) and bool(asks[0].get("answered"))),
                ("el historial cierra con la nota del proyecto",
                 kinds[-1] == "note"),
                ("sin ids repetidos", len(ids) == len(set(ids))),
            ])


raise SystemExit(asyncio.run(main()))
