"""Una peticion de permiso sin responder tiene que sobrevivir a que te vayas.

pi se queda bloqueado hasta que alguien conteste, asi que si la tarjeta no
vuelve al recargar la pagina, la sesion queda muerta sin manera de rescatarla.

Se habla con el puente por websocket, sin navegador: esto es del servidor.
Todo contra `fake_pi`; el agente de verdad no entra.
"""
import asyncio
import json

from harness import Bridge, FakeProject, PORT, Page, report

WS = "ws://127.0.0.1:%d/ws" % PORT


async def take(ws, want, seconds=6.0):
    """Espera un mensaje del tipo pedido y lo devuelve."""
    end = asyncio.get_event_loop().time() + seconds
    while asyncio.get_event_loop().time() < end:
        left = end - asyncio.get_event_loop().time()
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=left))
        except asyncio.TimeoutError:
            break
        if m.get("type") == want:
            return m
        if want == "item" and m.get("type") == "snapshot":
            continue
    return None


def asks(items):
    return [i for i in items if i.get("kind") == "ask"]


async def main():
    import websockets
    checks = []
    with Bridge(), FakeProject() as proj, FakeProject("otro") as otro:
        # --- se abre el proyecto y se deja una peticion en el aire
        async with websockets.connect(WS) as a:
            await take(a, "snapshot")
            await a.send(json.dumps({"type": "open_project",
                                     "path": proj.path}))
            await asyncio.sleep(1.2)
            await a.send(json.dumps({"type": "prompt",
                                     "message": "danger, por favor"}))
            ask = None
            for _ in range(40):
                m = json.loads(await asyncio.wait_for(a.recv(), timeout=6))
                if m.get("type") == "item" and m["item"].get("kind") == "ask":
                    ask = m["item"]
                    break
            print("  la peticion llega:", bool(ask),
                  (ask or {}).get("title"), (ask or {}).get("detail"))
            checks.append(("llega la peticion de permiso", ask is not None))

        # --- se cierra el navegador y se vuelve: el snapshot debe traerla
        async with websockets.connect(WS) as b:
            snap = await take(b, "snapshot")
            back = asks(snap.get("items", []))
            print("  al reconectar hay %d peticion(es), esperando=%s"
                  % (len(back), snap.get("state", {}).get("waiting")))
            checks += [
                ("al reconectar la peticion sigue ahi", len(back) == 1),
                ("con su rid, para poder contestarla",
                 bool(back) and back[0].get("rid") == ask.get("rid")),
                ("y el estado dice que se esta esperando",
                 snap.get("state", {}).get("waiting") is True),
            ]

            # --- y al volver a abrir el mismo proyecto, tambien
            await b.send(json.dumps({"type": "open_project",
                                     "path": proj.path}))
            await asyncio.sleep(2.0)
            async with websockets.connect(WS) as c:
                snap2 = await take(c, "snapshot")
                again = asks(snap2.get("items", []))
                print("  tras reabrir el proyecto: %d peticion(es),"
                      " esperando=%s"
                      % (len(again), snap2.get("state", {}).get("waiting")))
                checks += [
                    ("reabrir el mismo proyecto no la tira",
                     len(again) == 1),
                    ("y sigue siendo contestable",
                     bool(again) and again[0].get("rid") == ask.get("rid")),
                ]

                # --- y la pagina de verdad la pinta al abrirse
                async with Page(port=9398) as pg:
                    await pg.go()
                    await asyncio.sleep(0.8)
                    card = await pg.js(
                        "(() => { const a ="
                        " document.querySelector('.ask:not(.done)');"
                        " return a ? [a.querySelector('h3').textContent,"
                        " a.querySelectorAll('.opt').length,"
                        " !!a.querySelector('.what pre')] : null; })()")
                    row = await pg.js(
                        "[...document.querySelectorAll('.tool .nm')]"
                        ".map(s => s.textContent)")
                    print("  la pagina la pinta:", card)
                    print("  la fila dice: %r" % row)
                    checks.append(
                        ("la fila ensena el comando, no el json",
                         "bash rm -rf ./build 2>/dev/null" in row
                         and not any("{" in r for r in row)))
                    checks += [
                        ("al abrir la pagina la tarjeta esta ahi",
                         card is not None),
                        ("con sus opciones para poder contestar",
                         bool(card) and card[1] >= 3),
                        ("y con el comando que la provoco",
                         bool(card) and card[2] is True),
                    ]

                # --- contestarla la cierra de verdad
                await c.send(json.dumps({"type": "answer",
                                         "rid": ask.get("rid"),
                                         "choice": "Allow once"}))
                await asyncio.sleep(1.2)
                async with websockets.connect(WS) as d:
                    snap3 = await take(d, "snapshot")
                    done = asks(snap3.get("items", []))
                    print("  contestada: answered=%r esperando=%s"
                          % ((done or [{}])[0].get("answered"),
                             snap3.get("state", {}).get("waiting")))
                    tools = [i for i in snap3.get("items", [])
                             if i.get("kind") == "tool"]
                    print("  herramientas: %s"
                          % [(t.get("name"), t.get("status"))
                             for t in tools])
                    checks.append(
                        ("nada se queda en marcha al acabar el turno",
                         bool(tools) and all(t.get("status") != "running"
                                             for t in tools)))
                    checks += [
                        ("contestarla la marca como respondida",
                         bool(done) and done[0].get("answered")
                         == "Allow once"),
                        ("y deja de esperar",
                         snap3.get("state", {}).get("waiting") is False),
                    ]

        # --- compactar deja el contexto en otro sitio: la barra lo sabe
        async with websockets.connect(WS) as z:
            snap = await take(z, "snapshot")
            before = (snap.get("state") or {}).get("context") or {}
            await z.send(json.dumps({"type": "prompt",
                                     "message": "compact ahora"}))
            after = before
            end = asyncio.get_event_loop().time() + 12
            while asyncio.get_event_loop().time() < end:
                try:
                    m = json.loads(await asyncio.wait_for(z.recv(), timeout=3))
                except asyncio.TimeoutError:
                    continue
                if m.get("type") == "state":
                    c = (m.get("state") or {}).get("context") or {}
                    if c.get("tokens") == 5200:
                        after = c
                        break
            print("  contexto: %s -> %s"
                  % (before.get("tokens"), after.get("tokens")))
            print("  porcentaje: %s -> %s"
                  % (before.get("percent"), after.get("percent")))
            checks += [
                ("compactar mueve la barra", after.get("tokens") == 5200),
                ("con su porcentaje, no en blanco",
                 isinstance(after.get("percent"), (int, float))
                 and after["percent"] < (before.get("percent") or 100)),
            ]

        # --- irse a otro proyecto si mata al pi que esperaba: hay que decirlo
        async with websockets.connect(WS) as e:
            await take(e, "snapshot")
            await e.send(json.dumps({"type": "prompt",
                                     "message": "danger otra vez"}))
            for _ in range(40):
                m = json.loads(await asyncio.wait_for(e.recv(), timeout=6))
                if m.get("type") == "item" and m["item"].get("kind") == "ask":
                    break
            await e.send(json.dumps({"type": "open_project",
                                     "path": otro.path}))
            await asyncio.sleep(2.0)
            async with websockets.connect(WS) as f:
                snap4 = await take(f, "snapshot")
                items = snap4.get("items", [])
                warned = [i for i in items
                          if i.get("key") == "dropped_ask"]
                print("  al cambiar de proyecto: %d peticion(es), aviso=%r"
                      % (len(asks(items)),
                         (warned or [{}])[0].get("text")))
                checks += [
                    ("cambiar de proyecto si la tira", asks(items) == []),
                    ("pero lo dice, en vez de callarselo",
                     len(warned) == 1 and warned[0].get("level") == "warn"),
                ]
    return checks


if __name__ == "__main__":
    report(asyncio.run(main()))
