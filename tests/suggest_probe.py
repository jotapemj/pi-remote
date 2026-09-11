"""Sugerencias de respuesta. Con el toggle activo, el puente inyecta una
instruccion oculta en el prompt (no en la burbuja del usuario); el modelo
acaba con hasta 3 marcadores <hint:...> que el cliente NO muestra (visibleText)
y pinta como filas bajo la respuesta. Clic en una fila la envia directamente.
Apagado, nada de esto pasa. Sin agente real: fake_pi responde con los
marcadores si ve la instruccion.
"""
import asyncio
import json

import websockets

from harness import Bridge, FakeProject, Page, report, WS_URL


async def passthrough():
    """El puente inyecta la instruccion a pi pero deja la burbuja limpia."""
    user, said = None, ""
    with FakeProject() as proj, Bridge():
        async with websockets.connect(WS_URL) as ws:
            await ws.recv()
            await ws.send(json.dumps({"type": "open_project", "path": proj.path}))
            await asyncio.sleep(1.2)
            await ws.send(json.dumps({"type": "prompt", "message": "hola",
                                      "suggest": True}))
            end = asyncio.get_event_loop().time() + 5
            while asyncio.get_event_loop().time() < end:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 2))
                except asyncio.TimeoutError:
                    break
                it = m.get("item") or {}
                if it.get("kind") == "user":
                    user = it.get("text")
                if it.get("kind") == "assistant":
                    said += it.get("text", "")
                if m.get("type") == "delta":
                    said += m.get("delta", "")
    print("  puente: burbuja=%r  respuesta lleva <hint:>=%s"
          % (user, "<hint:" in said))
    return [
        ("la burbuja del usuario queda limpia (sin la instruccion)",
         user == "hola"),
        ("pi recibio la instruccion (respondio con el marcador)",
         "<hint:" in said),
    ]


REPLY = ("Hecho. Cuando digas, push."
         "\\n<hint: Vale, haz el push.>"
         "\\n<hint: Espera, revisa antes.>"
         "\\n<hint: Muestrame el diff.>")


async def in_page():
    checks = []
    with Bridge():
        async with Page(port=9380) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")
            await js("state={running:false,waiting:false,alive:true,cwd:'C:/x',"
                     "sessionName:'s',model:'m',thinking:'x',context:null,"
                     "queue:{steering:[],followUp:[]},recent:[]}; paint()")
            await js("setSuggest(true)")

            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:1, kind:'assistant', streaming:false,"
                     " text:'%s'}); placeActions();" % REPLY)
            await asyncio.sleep(0.1)

            shown = await js("document.querySelector('.said,[data-body]')"
                             ".textContent")
            print("  render: mostrado=%r" % shown)
            checks += [
                ("el marcador no se muestra",
                 "<hint" not in shown and "Vale, haz el push" not in shown),
                ("el texto normal si se ve", "Cuando digas, push" in shown),
            ]

            rows = await js("[...document.querySelectorAll("
                            "'.suggests .sug .stext')].map(n=>n.textContent)")
            arrows = await js("document.querySelectorAll("
                              "'.suggests .sug .sarrow .i').length")
            print("  filas: %s  flechas=%s" % (rows, arrows))
            checks += [
                ("aparecen 3 filas de sugerencia", len(rows) == 3),
                ("con los textos propuestos, sin el marcador",
                 rows == ["Vale, haz el push.", "Espera, revisa antes.",
                          "Muestrame el diff."]),
                ("cada fila lleva su flechita", arrows == 3),
            ]

            # clic en la 2a fila -> envia ese mensaje, con la bandera
            await js("window.__sent=[];"
                     " ws.send = s => window.__sent.push(JSON.parse(s));"
                     " document.querySelectorAll('.suggests .sug')[1].click()")
            await asyncio.sleep(0.1)
            sent = await js("(() => { const m = window.__sent.find("
                            "x => x.type==='prompt'); return m ? [m.message,"
                            " m.suggest === true] : null;})()")
            cleared = await js("box.value")
            gone = await js("!document.querySelector('.suggests')")
            print("  clic: enviado=%s box=%r filas_fuera=%s"
                  % (sent, cleared, gone))
            checks += [
                ("clic en una sugerencia la envia con la bandera",
                 bool(sent) and sent[0] == "Espera, revisa antes."
                 and sent[1] is True),
                ("y limpia el compositor", cleared == ""),
                ("y retira las filas al enviar", gone is True),
            ]

            # el toggle pinta o quita las filas
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:2, kind:'assistant', streaming:false,"
                     " text:'%s'}); setSuggest(true)" % REPLY)
            await asyncio.sleep(0.05)
            on_n = await js("document.querySelectorAll('.suggests .sug').length")
            await js("setSuggest(false)")
            await asyncio.sleep(0.05)
            off_n = await js("document.querySelectorAll('.suggests .sug').length")
            print("  toggle: on=%s off=%s" % (on_n, off_n))
            checks += [
                ("con el toggle activo hay filas", on_n == 3),
                ("apagado, no hay filas", off_n == 0),
            ]

            # al activar desde la card, dialog de aviso (orden oculta + contexto)
            await js("paintSheet('functions')")
            await js("(() => { const c = [...document.querySelectorAll('#sheetBody .fcard')]"
                     ".find(c => c.textContent.includes('Sugerencias'));"
                     " const s = c && c.querySelector('.sw');"
                     " if(s) s.click(); })()")
            await asyncio.sleep(0.05)
            warn = await js("[document.querySelector('#modal').classList.contains('open'),"
                            " document.querySelector('#modal').textContent]")
            print("  aviso: abierto=%s texto=%r" % (warn and warn[0],
                  (warn and warn[1] or "")[:70]))
            checks += [
                ("al activar la card, dialog de aviso",
                 bool(warn) and warn[0] is True and "contexto" in warn[1]),
            ]
            await js("document.querySelector('#modal').classList.remove('open')")

            # cola parcial en su propia linea no parpadea (se retiene al strea)
            await js("setSuggest(true); feed.innerHTML=''; nodes.clear();"
                     " render({id:3, kind:'assistant', streaming:true,"
                     " text:'Listo\\n<hin'})")
            await asyncio.sleep(0.05)
            part = await js("document.querySelector('.said,[data-body]')"
                            ".textContent")
            print("  parcial: mostrado=%r" % part)
            checks.append(("una cola parcial <hin no se muestra",
                           "<hin" not in part and "Listo" in part))

            # colision: un <hint:> EN MEDIO de la prosa (el modelo explicando la
            # feature) no se oculta ni genera filas. Antes cortaba el texto.
            await js("setSuggest(true); feed.innerHTML=''; nodes.clear();"
                     " render({id:4, kind:'assistant', streaming:false,"
                     " text:'Cierro con tres lineas <hint: ejemplo> y sigo "
                     "explicando aqui.'}); placeActions()")
            await asyncio.sleep(0.05)
            body = await js("document.querySelector('.said,[data-body]')"
                            ".textContent")
            rows = await js("document.querySelectorAll('.suggests .sug').length")
            print("  colision: filas=%s body=%r" % (rows, body))
            checks += [
                ("un <hint:> en prosa no genera filas", rows == 0),
                ("y no corta el texto tras el marcador",
                 "Cierro con tres lineas" in body and "sigo explicando" in body),
            ]

            # formas XML al final: etiqueta cerrada <hint>...</hint>
            await js("setSuggest(true); feed.innerHTML=''; nodes.clear();"
                     " render({id:5, kind:'assistant', streaming:false,"
                     " text:'Listo.\\n"
                     "<hint>Una cosa</hint>\\n"
                     "<hint>Otra cosa</hint>\\n"
                     "<hint>Tercera cosa</hint>'}); placeActions()")
            await asyncio.sleep(0.05)
            shown = await js("document.querySelector('.said,[data-body]')"
                             ".textContent")
            rows = await js("[...document.querySelectorAll("
                            "'.suggests .sug .stext')].map(n=>n.textContent)")
            print("  xml cerrado: filas=%s body=%r" % (rows, shown))
            checks += [
                ("etiquetas cerradas al final dan 3 filas",
                 rows == ["Una cosa", "Otra cosa", "Tercera cosa"]),
                ("y el cuerpo no muestra las etiquetas",
                 "<hint" not in shown and "</hint>" not in shown
                 and "Listo." in shown),
            ]

            # abierta sin cierre (el modelo se olvida del </hint>) + canonica
            await js("setSuggest(true); feed.innerHTML=''; nodes.clear();"
                     " render({id:6, kind:'assistant', streaming:false,"
                     " text:'Hecho.\\n"
                     "<hint>Sin cierre uno\\n"
                     "<hint: con dos puntos>'}); placeActions()")
            await asyncio.sleep(0.05)
            shown = await js("document.querySelector('.said,[data-body]')"
                             ".textContent")
            rows = await js("[...document.querySelectorAll("
                            "'.suggests .sug .stext')].map(n=>n.textContent)")
            print("  mixto: filas=%s body=%r" % (rows, shown))
            checks += [
                ("abierta sin cierre + canonica dan 2 filas",
                 rows == ["Sin cierre uno", "con dos puntos"]),
                ("y el cuerpo queda limpio",
                 "Hecho." in shown and "<hint" not in shown),
            ]

            # abierta con un > de cierre suelto (el modelo cierra con > en vez
            # de </hint>): el texto no debe arrastrar ese > final (bug de la foto)
            await js("setSuggest(true); feed.innerHTML=''; nodes.clear();"
                     " render({id:9, kind:'assistant', streaming:false,"
                     " text:'Hecho.\\n"
                     "<hint>Los nombres se actualizan.>\\n"
                     "<hint>Sigue mostrando viejos.>'}); placeActions()")
            await asyncio.sleep(0.05)
            rows = await js("[...document.querySelectorAll("
                            "'.suggests .sug .stext')].map(n=>n.textContent)")
            print("  cierre suelto: filas=%s" % rows)
            checks += [
                ("un > de cierre suelto no queda en el texto del hint",
                 rows == ["Los nombres se actualizan.",
                          "Sigue mostrando viejos."]),
            ]

            # colision: etiqueta cerrada EN MEDIO de la prosa se ve como texto
            await js("setSuggest(true); feed.innerHTML=''; nodes.clear();"
                     " render({id:7, kind:'assistant', streaming:false,"
                     " text:'Uso <hint>etiqueta</hint> para marcar y sigo.'});"
                     " placeActions()")
            await asyncio.sleep(0.05)
            body = await js("document.querySelector('.said,[data-body]')"
                            ".textContent")
            rows = await js("document.querySelectorAll('.suggests .sug').length")
            print("  colision xml: filas=%s body=%r" % (rows, body))
            checks += [
                ("etiqueta cerrada en prosa no genera filas", rows == 0),
                ("y se ve como texto",
                 "Uso <hint>etiqueta</hint> para marcar" in body),
            ]

            # streaming: cola parcial con forma XML se retiene, no parpadea
            await js("setSuggest(true); feed.innerHTML=''; nodes.clear();"
                     " render({id:8, kind:'assistant', streaming:true,"
                     " text:'Listo\\n<hint>haz'})")
            await asyncio.sleep(0.05)
            part = await js("document.querySelector('.said,[data-body]')"
                            ".textContent")
            rows = await js("document.querySelectorAll('.suggests .sug').length")
            print("  parcial xml: mostrado=%r filas=%s" % (part, rows))
            checks += [
                ("una cola parcial <hint>haz no se muestra ni da filas",
                 "<hint" not in part and "Listo" in part and rows == 0),
            ]

            checks.append(("sin errores de consola", not p.problems))
    return checks


async def main():
    checks = await passthrough()
    checks += await in_page()
    return checks


raise SystemExit(report(asyncio.run(main())))
