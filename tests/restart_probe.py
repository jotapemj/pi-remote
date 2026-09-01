"""Que sobrevive a matar el puente y volver a levantarlo."""
import asyncio
import json

import websockets

from harness import Bridge, FakeProject, PORT, report, WS_URL

WS = WS_URL


async def snapshot(want_items=False):
    """El historial llega poco despues del primer snapshot: hay que esperarlo."""
    async with websockets.connect(WS) as ws:
        snap = json.loads(await ws.recv())
        if not want_items:
            return snap
        end = asyncio.get_event_loop().time() + 6
        while asyncio.get_event_loop().time() < end:
            if any(i["kind"] == "user" for i in snap["items"]):
                return snap
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), 1.5))
            except asyncio.TimeoutError:
                break
            if m["type"] == "snapshot":
                snap = m
        return snap


async def open_project(path):
    async with websockets.connect(WS) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "open_project", "path": path}))
        for _ in range(60):
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m["type"] == "state" and \
                    m["state"].get("cwd", "").lower() == path.lower():
                return m["state"]
    raise AssertionError("no abrio " + path)


async def main():
    with FakeProject("uno") as a, FakeProject("dos") as b:
        state = None
        checks = []

        # --------- primera vida ---------
        with Bridge(cleanup=False) as br:
            state = br.state
            snap = await snapshot()
            checks.append(("arranca sin nada",
                           snap["cwd"] == ""
                           and snap["state"]["recent"] == []))
            await open_project(a.path)
            st = await open_project(b.path)
            print("  vida 1, tras abrir dos:",
                  [r["name"] for r in st["recent"]])
            keep = json.loads(state.read_text(encoding="utf-8"))

        print("  --- puente matado ---")

        # --------- segunda vida, con el estado de la primera ---------
        with Bridge(state=state, fresh=False, cleanup=False):
            snap = await snapshot(want_items=True)
            rec = [r["name"] for r in snap["state"]["recent"]]
            print("  vida 2, recientes    :", rec)
            print("  vida 2, proyecto     :", snap["cwd"] == b.path)
            checks.append(("los recientes sobreviven", len(rec) == 2))
            checks.append(("reabre el ultimo proyecto",
                           snap["cwd"].lower() == b.path.lower()))
            checks.append(("y trae su historial",
                           any(i["kind"] == "user" for i in snap["items"])))

        # --------- una carpeta que ya no existe ---------
        keep["recent"].insert(1, str(a.dir) + "-que-no-existe")
        state.write_text(json.dumps(keep), encoding="utf-8")
        with Bridge(state=state, fresh=False):
            snap = await snapshot()
            rec = [r["name"] for r in snap["state"]["recent"]]
            print("  vida 3, con una borrada:", len(rec), "de 3")
            checks.append(("descarta la carpeta que ya no existe",
                           len(rec) == 2))

        return report(checks)


raise SystemExit(asyncio.run(main()))
