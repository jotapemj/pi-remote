"""Proyectos recientes: orden por uso, sin duplicados, y quitarlos."""
import asyncio
import json

import websockets

from harness import Bridge, FakeProject, PORT, report

WS = "ws://127.0.0.1:%d/ws" % PORT


async def wait_cwd(ws, want):
    for _ in range(60):
        m = json.loads(await asyncio.wait_for(ws.recv(), 15))
        if m["type"] == "state" and \
                m["state"].get("cwd", "").lower() == want.lower():
            return m["state"]
    raise AssertionError("no cambio a " + want)


async def forget(ws, path, want):
    await ws.send(json.dumps({"type": "forget_project", "path": path}))
    end = asyncio.get_event_loop().time() + 4
    last = None
    while asyncio.get_event_loop().time() < end:
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), 1.2))
        except asyncio.TimeoutError:
            break
        if m["type"] == "state":
            last = [r["name"] for r in m["state"]["recent"]]
            if len(last) == want:
                break
    return last


async def main():
    with FakeProject("uno") as a, FakeProject("dos") as b:
        with Bridge() as bridge:
            async with websockets.connect(WS) as ws:
                snap = json.loads(await ws.recv())
                print("  arranque   : cwd=%r recientes=%d"
                      % (snap["cwd"], len(snap["state"]["recent"])))

                await ws.send(json.dumps({"type": "open_project",
                                          "path": a.path}))
                await wait_cwd(ws, a.path)
                await ws.send(json.dumps({"type": "open_project",
                                          "path": b.path}))
                st = await wait_cwd(ws, b.path)
                dos = [r["name"] for r in st["recent"]]
                print("  dos abiertos:", dos)

                await ws.send(json.dumps({"type": "open_project",
                                          "path": a.path}))
                st = await wait_cwd(ws, a.path)
                reorder = [r["name"] for r in st["recent"]]
                print("  reabierto A :", reorder)

                keep = await forget(ws, a.path, 2)
                print("  quitar el abierto:", keep, "(no debe cambiar)")
                gone = await forget(ws, b.path, 1)
                print("  quitar el otro   :", gone)

            disk = json.loads(bridge.state.read_text(encoding="utf-8"))

            return report([
                ("arranca sin nada",
                 snap["cwd"] == "" and snap["state"]["recent"] == []),
                ("recuerda los dos", len(dos) == 2),
                ("el ultimo usado va primero", reorder[0] == dos[1]),
                ("sin duplicados", len(reorder) == len(set(reorder))),
                ("el proyecto abierto no se puede quitar",
                 keep is None or len(keep) == 2),
                ("los demas si", gone is not None and len(gone) == 1),
                ("y queda escrito en disco",
                 len(disk.get("recent", [])) == 1),
            ])


raise SystemExit(asyncio.run(main()))
