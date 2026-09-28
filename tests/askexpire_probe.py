"""Tarjetas de permiso que pi cierra solo. Un dialogo con `timeout` pi lo
resuelve al vencer, y uno con senal de aborto al abortarse, sin decirle nada
al host: la tarjeta se quedaba abierta para siempre, con `waiting` en true y
la lectura oculta. Ahora caduca al vencer el timeout, o al asentarse el turno
en que nacio (un dialogo bloquea su turno: si el turno asento, ya no lo
espera nadie). Uno contestado sigue siendo contestado. Contra fake_pi.
"""
import asyncio
import json

from harness import Bridge, FakeProject, Page, WS_URL, report


async def drain(ws, seconds):
    """Todos los mensajes que lleguen en ese rato."""
    got = []
    end = asyncio.get_event_loop().time() + seconds
    while True:
        left = end - asyncio.get_event_loop().time()
        if left <= 0:
            break
        try:
            got.append(json.loads(await asyncio.wait_for(ws.recv(), left)))
        except asyncio.TimeoutError:
            break
    return got


def ask_of(msgs):
    for m in msgs:
        if m.get("type") == "item" and m["item"].get("kind") == "ask":
            return m["item"]
    return None


def expired(msgs, item_id):
    return any(m.get("type") == "patch" and m.get("id") == item_id
               and m.get("fields", {}).get("expired") for m in msgs)


def waiting(msgs):
    st = [m["state"].get("waiting") for m in msgs if m.get("type") == "state"]
    return st[-1] if st else None


async def run(ws, proj, text, first, then):
    """Los tiempos cuentan desde que llega la tarjeta, no desde el prompt:
    antes el fake streamea texto y herramientas."""
    await ws.send(json.dumps({"type": "prompt", "message": text}))
    a = []
    for _ in range(100):
        a += await drain(ws, 0.1)
        if ask_of(a):
            break
    a += await drain(ws, first)
    b = await drain(ws, then)
    return ask_of(a), a, b


async def main():
    import websockets
    checks = []
    with Bridge(), FakeProject() as proj:
        async with websockets.connect(WS_URL) as ws:
            await drain(ws, 0.5)
            await ws.send(json.dumps({"type": "open_project",
                                      "path": proj.path}))
            await drain(ws, 1.5)

            # timeout de 700 ms: caduca por el temporizador, antes del fin
            # del turno (el fake asienta a los 1,2 s)
            ask, a, b = await run(ws, proj, "askexpire", 0.9, 1.0)
            print("  timeout: ask=%s caduca_antes=%s luego=%s waiting=%s"
                  % (bool(ask), expired(a, ask and ask["id"]),
                     expired(b, ask and ask["id"]), waiting(a + b)))
            checks += [
                ("llega la tarjeta", ask is not None),
                ("al vencer el timeout caduca, sin esperar al turno",
                 expired(a, ask["id"])),
                ("y ya no se espera nada", waiting(a + b) is False),
            ]

            # sin timeout, el turno asienta con el dialogo abierto (senal de
            # aborto): caduca al asentar
            ask2, a2, b2 = await run(ws, proj, "askabort", 0.4, 1.2)
            print("  aborto: ask=%s abierta_al_principio=%s caduca=%s"
                  % (bool(ask2), not expired(a2, ask2 and ask2["id"]),
                     expired(b2, ask2 and ask2["id"])))
            checks += [
                ("mientras el turno corre, la tarjeta sigue abierta",
                 ask2 is not None and not expired(a2, ask2["id"])),
                ("al asentarse el turno, caduca",
                 expired(b2, ask2["id"]) and waiting(b2) is False),
            ]

            # la que se contesta no caduca, y contestar una caducada no
            # manda nada a pi (el rid ya no esta pendiente)
            ask3, a3, _ = await run(ws, proj, "danger", 0.1, 0.1)
            await ws.send(json.dumps({"type": "answer", "rid": ask3["rid"],
                                      "choice": "Deny"}))
            b3 = await drain(ws, 1.0)
            ans = [m for m in b3 if m.get("type") == "patch"
                   and m.get("id") == ask3["id"]]
            checks.append(("una contestada queda contestada, no caducada",
                           ans and ans[0]["fields"].get("answered")
                           and not expired(b3, ask3["id"])))

            # recargar: la caducada no vuelve como pendiente
            async with websockets.connect(WS_URL) as w2:
                snap = [m for m in await drain(w2, 0.8)
                        if m.get("type") == "snapshot"][0]
                back = {i["id"]: i for i in snap["items"]
                        if i.get("kind") == "ask"}
                checks.append(("al reconectar, la caducada sigue cerrada",
                               back.get(ask["id"], {}).get("expired") is True
                               and snap["state"].get("waiting") is False))

        # la tarjeta pintada: sin botones y con su veredicto gris
        async with Page() as p:
            await p.go()
            await asyncio.sleep(1.0)
            await p.js("setLang('es')")
            ui = await p.js("""(() => {
              render({id: 900, kind: 'ask', rid: 'r', method: 'confirm',
                      title: 'Proceed?', expired: true});
              const el = nodes.get(900), v = el.querySelector('.verdict');
              const ic = v && v.querySelector('path');
              return {done: el.querySelector('.ask').classList.contains('done'),
                      icon: ic ? ic.getAttribute('d').slice(0, 12) : null,
                      opts: getComputedStyle(el.querySelector('.opts')).display,
                      text: v && v.textContent.trim(),
                      grey: v && getComputedStyle(v).color
                        !== getComputedStyle(document.querySelector(
                          '.ask .verdict:not(.expired)') || document.body).color};
            })()""")
            print("  ", ui)
            checks += [
                ("caducada: sin botones", ui["done"] and ui["opts"] == "none"),
                ("con su rotulo traducido",
                 ui["text"] == "cerrada sin respuesta"),
                ("con el icono history_toggle_off",
                 ui["icon"] == "M15.1,19.37l"),
            ]
    return checks


raise SystemExit(report(asyncio.run(main())))
