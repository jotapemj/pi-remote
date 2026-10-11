"""Tarjetas de permiso que pi cierra solo. Un dialogo con `timeout` pi lo
resuelve al vencer, y uno con senal de aborto al abortarse, sin decirle nada
al host: la tarjeta se quedaba abierta para siempre, con `waiting` en true y
la lectura oculta. Ahora caduca al vencer el timeout, o al asentarse el turno
en que nacio (un dialogo bloquea su turno: si el turno asento, ya no lo
espera nadie). Uno contestado sigue siendo contestado, y ahora se compacta a dos lineas
(titulo + respuesta) con un chevron a la derecha; el detalle queda dentro.
Contra fake_pi.
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

            # cancelada: el puente lo anota (el cliente la pinta en coral)
            ask4, _, _ = await run(ws, proj, "danger", 0.1, 0.1)
            await ws.send(json.dumps({"type": "answer", "rid": ask4["rid"],
                                      "choice": "__cancel__"}))
            b4 = await drain(ws, 1.0)
            cx = [m for m in b4 if m.get("type") == "patch"
                  and m.get("id") == ask4["id"]]
            print("  cancelada:", cx and cx[0]["fields"])
            checks.append(("cancelada: el puente lo anota",
                           cx and cx[0]["fields"].get("cancelled") is True
                           and cx[0]["fields"].get("answered") == "cancelled"))

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
              render({id: 904, kind: 'ask', rid: 'ok', method: 'confirm',
                      title: 'Allow?', answered: 'yes'});
              render({id: 900, kind: 'ask', rid: 'r', method: 'confirm',
                      title: 'Proceed?', expired: true});
              const a = nodes.get(900).querySelector('.ask');
              const b = nodes.get(904).querySelector('.ask');
              const q = a.querySelector('.qans'), w = b.querySelector('.qans');
              const ic = q.querySelector('path');
              return {tag: a.tagName, open: a.open,
                      top: a.querySelector('.qtop').textContent,
                      ans: q.textContent.trim(),
                      icon: ic.getAttribute('d').slice(0, 12),
                      opts: !a.querySelector('.opts'),
                      grey: getComputedStyle(q).color
                            != getComputedStyle(w).color,
                      green: getComputedStyle(w).color
                             == getComputedStyle(
                               b.querySelector('.verdict')).color};
            })()""")
            print("  ", ui)
            # titulo de varias lineas (pi-permission-system mete el detalle
            # en el titulo): la primera es el titulo, el resto detalle, sin
            # la linea que repite el comando del bloque de abajo
            ml = await p.js("""(() => {
              render({id: 901, kind: 'ask', rid: 'm', method: 'select',
                title: 'Permission Required\\ntool: bash\\n' +
                  'command: ls ~/.claude\\nexternal path: c:\\\\users\\\\x',
                options: ['Yes', 'No'], tool: 'bash', detail: 'ls ~/.claude'});
              render({id: 902, kind: 'ask', rid: 'o', method: 'confirm',
                title: 'Allow?'});
              const a = nodes.get(901), b = nodes.get(902);
              return {h3: a.querySelector('h3').textContent,
                      meta: (a.querySelector('.askmeta') || {}).textContent,
                      one: b.querySelector('h3').textContent,
                      noMeta: !b.querySelector('.askmeta')}; })()""")
            print("  ", ml)
            checks += [
                ("titulo multilinea: la primera linea es el titulo",
                 ml["h3"] == "Permission Required"),
                ("el resto va como detalle, renglon a renglon",
                 ml["meta"] == "tool: bash\nexternal path: c:\\users\\x"),
                ("un titulo de una linea queda igual",
                 ml["one"] == "Allow?" and ml["noMeta"]),
            ]
            # respuesta escrita: dialogo propio, no el prompt() del navegador
            ti = await p.js("""(() => {
              const sent = []; const s0 = ws.send.bind(ws);
              ws.send = x => { sent.push(JSON.parse(x)); };
              let native = false; const p0 = window.prompt;
              window.prompt = () => { native = true; return null; };
              render({id: 903, kind: 'ask', rid: 'rr', method: 'input',
                title: 'Permission Required\\nShare why this request was denied (optional).',
                prefill: 'sugerido'});
              nodes.get(903).querySelector('.opt[data-c="__text__"]').click();
              const r = {native, open: $('#modal').classList.contains('open'),
                title: $('#modalTitle').textContent,
                body: $('#modalBody').textContent,
                val: ($('#modalInput') || {}).value};
              $('#modalInput').value = 'uses a slow path';
              $('#modalOk').click();
              r.sent = sent.filter(o => o.type === 'answer');
              ws.send = s0; window.prompt = p0;
              return r; })()""")
            print("  respuesta escrita:", ti)
            checks += [
                ("escribir la respuesta abre el dialogo propio, no prompt()",
                 ti["open"] and not ti["native"]),
                ("titulo = primera linea; cuerpo = el resto",
                 ti["title"] == "Permission Required"
                 and "Share why this request was denied" in ti["body"]),
                ("con el texto sugerido ya puesto", ti["val"] == "sugerido"),
                ("y lo escrito viaja como respuesta",
                 ti["sent"] and ti["sent"][0]["rid"] == "rr"
                 and ti["sent"][0]["choice"] == "uses a slow path"),
            ]
            # contestada: se compacta a dos lineas, chevron a la derecha
            cp = await p.js("""(() => {
              render({id: 910, kind: 'ask', rid: 'm', method: 'select',
                title: 'Permission Required\\ncommand: ls ~/.claude',
                options: ['Yes','No'], tool: 'bash', detail: 'ls ~/.claude',
                answered: 'allow for this session'});
              const a = nodes.get(910).querySelector('.ask');
              const s = a.querySelector('summary'), tw = s.querySelector('.tw');
              const r = {tag: a.tagName, open: a.open,
                top: s.querySelector('.qtop').textContent,
                ans: s.querySelector('.qans').textContent.trim(),
                chev: !!tw,
                right: tw.getBoundingClientRect().left
                       > s.querySelector('.qtop').getBoundingClientRect().right,
                h: Math.round(a.getBoundingClientRect().height),
                noOpts: !a.querySelector('.opts')};
              s.click();
              r.opened = a.open;
              r.rot = getComputedStyle(tw).transform !== 'none';
              r.cap = a.querySelector('.cap').textContent;
              r.noH3 = !a.querySelector('h3');
              r.what = !!a.querySelector('.what');
              r.verdict = a.querySelector('.verdict').textContent.trim();
              return r; })()""")
            print("  compacta:", cp)
            checks += [
                ("contestada: compacta, cerrada",
                 cp["tag"] == "DETAILS" and not cp["open"]),
                ("linea 1: el titulo", cp["top"] == "Permission Required"),
                ("linea 2: la respuesta dada",
                 cp["ans"] == "respondido: allow for this session"),
                ("chevron a la derecha", cp["chev"] and cp["right"]),
                ("fila compacta (< 60 px)", cp["h"] < 60),
                ("la fila entera abre", cp["opened"]),
                ("el chevron rota al abrir", cp["rot"]),
                ("el detalle queda dentro",
                 cp["cap"] == "pi pregunta" and cp["what"]),
                ("el titulo no se repite al abrir", cp["noH3"]),
                ("la respuesta entera al abrir",
                 cp["verdict"] == "respondido: allow for this session"),
            ]
            # respuesta larga: truncada en la fila, entera al abrir
            lg = await p.js("""(() => {
              render({id: 911, kind: 'ask', rid: 'L', method: 'confirm',
                title: 'Allow?', answered: 'no, el comando toca ficheros '
                  + 'fuera del proyecto y la carpeta no esta confiada'});
              const a = nodes.get(911).querySelector('.ask');
              const sp = a.querySelector('.qans > span');
              const r = {clip: sp.scrollWidth > sp.clientWidth};
              a.querySelector('summary').click();
              r.full = a.querySelector('.verdict').textContent.trim().length;
              return r; })()""")
            print("  respuesta larga:", lg)
            checks += [
                ("respuesta larga: truncada en la fila", lg["clip"]),
                ("y entera al abrir", lg["full"] > 40),
            ]
            # cancelada: coral, no verde (el pixel pintado, contra el token)
            cx = await p.js("""(() => {
              render({id: 912, kind: 'ask', rid: 'x', method: 'confirm',
                title: 'Allow?', answered: 'cancelled', cancelled: true});
              const a = nodes.get(912).querySelector('.ask');
              const q = a.querySelector('.qans');
              const ref = document.createElement('span');
              ref.style.color = 'var(--coral)';
              document.body.appendChild(ref);
              const r = {coral: getComputedStyle(q).color
                         == getComputedStyle(ref).color,
                        notMint: getComputedStyle(q).color
                         != getComputedStyle(nodes.get(910)
                           .querySelector('.qans')).color,
                        ans: q.textContent.trim(),
                        verdict: a.querySelector('.verdict').textContent.trim(),
                        icon: q.querySelector('path').getAttribute('d')
                              .slice(0, 9)};
              ref.remove();
              return r; })()""")
            print("  cancelada UI:", cx)
            checks += [
                ("cancelada: en coral, no en verde",
                 cx["coral"] and cx["notMint"]),
                ("con su X y el texto de la respuesta",
                 cx["ans"] == "respondido: cancelled"
                 and cx["verdict"] == "respondido: cancelled"
                 and cx["icon"] == "m330-288 "),
            ]
            checks += [
                ("caducada: sin botones", ui["opts"]),
                ("caducada: compacta, cerrada",
                 ui["tag"] == "DETAILS" and not ui["open"]
                 and ui["top"] == "Proceed?"),
                ("con su rotulo traducido",
                 ui["ans"] == "cerrada sin respuesta"),
                ("con el icono history_toggle_off",
                 ui["icon"] == "M15.1,19.37l"),
                ("caducada en gris, contestada en verde",
                 ui["grey"] and ui["green"]),
            ]
    return checks


raise SystemExit(report(asyncio.run(main())))
