"""Fork desde un mensaje anterior. pi trunca en ese punto y hace rebindSession
(rama nueva sin los posteriores). El puente debe reaccionar como en un cambio de
sesion: limpiar el transcripto y reconstruir el historial. Antes era mudo y el
feed seguia mostrando los mensajes viejos. Sin agente real: fake_pi responde al
fork con cancelled=false y devuelve su historial en get_messages.
"""
import asyncio
import json

import websockets

from harness import Bridge, FakeProject, report, WS_URL


async def main():
    cleared = rebuilt = False
    with FakeProject() as proj, Bridge():
        async with websockets.connect(WS_URL) as ws:
            await ws.recv()                                  # snapshot inicial
            await ws.send(json.dumps({"type": "open_project", "path": proj.path}))
            await asyncio.sleep(1.5)
            try:                                             # vaciar lo del abrir
                while True:
                    await asyncio.wait_for(ws.recv(), 0.3)
            except asyncio.TimeoutError:
                pass

            await ws.send(json.dumps({"type": "fork", "entryId": "e1"}))
            end = asyncio.get_event_loop().time() + 4
            while asyncio.get_event_loop().time() < end:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 2))
                except asyncio.TimeoutError:
                    break
                ty = m.get("type")
                if ty == "cleared":
                    cleared = True
                elif cleared and ty in ("snapshot", "item"):
                    rebuilt = True
    print("  fork: cleared=%s rebuilt=%s" % (cleared, rebuilt))
    return [
        ("fork limpia el transcripto (emite cleared)", cleared),
        ("y reconstruye el historial tras limpiar", rebuilt),
    ]


raise SystemExit(report(asyncio.run(main())))
