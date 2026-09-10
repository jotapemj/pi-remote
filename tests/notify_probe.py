"""Notificaciones: card en Functions, revision del tipo de conexion con un
dialog, y aviso local al terminar el turno solo si la pestana no se ve. Sin
push ni terceros. Se mockea la API Notification del navegador.
"""
import asyncio

from harness import Bridge, Page, report


async def main():
    checks = []
    with Bridge():
        async with Page(port=9384) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")
            await js("state={running:false,waiting:false,alive:true,cwd:'C:/x',"
                     "sessionName:'mi sesion',model:'m',thinking:'x',"
                     "context:null,queue:{steering:[],followUp:[]},recent:[]};"
                     " paint()")

            # caso 1: conexion insegura -> dialog, no activa
            await js("Object.defineProperty(window,'isSecureContext',"
                     "{value:false,configurable:true});"
                     " document.querySelector('#modal').classList.remove('open');"
                     " setNotify(false); window.__ok=null;"
                     " requestNotify(function(ok){window.__ok=ok;})")
            await asyncio.sleep(0.05)
            d1 = await js("[document.querySelector('#modal')"
                          ".classList.contains('open'),"
                          " document.querySelector('#modalBody').textContent,"
                          " window.__ok, notify]")
            print("  no-seguro: abierto=%s ok=%s notify=%s" % (d1[0], d1[2], d1[3]))
            checks += [
                ("sin HTTPS abre un dialog", d1[0] is True),
                ("el dialog menciona HTTPS/segura",
                 "HTTPS" in d1[1] or "segura" in d1[1]),
                ("no activa sin conexion segura",
                 d1[2] is False and d1[3] is False),
            ]

            # caso 2: seguro + permiso concedido -> activa
            await js("document.querySelector('#modal').classList.remove('open');"
                     " Object.defineProperty(window,'isSecureContext',"
                     "{value:true,configurable:true});"
                     " window.Notification=function(t,o){window.__n={t:t,o:o};};"
                     " window.Notification.permission='granted';"
                     " window.Notification.requestPermission=function(){"
                     "return Promise.resolve('granted');};"
                     " window.__ok=null;"
                     " requestNotify(function(ok){window.__ok=ok;})")
            await asyncio.sleep(0.1)
            c2 = await js("[window.__ok, notify]")
            print("  concedido: ok=%s notify=%s" % tuple(c2))
            checks.append(("permiso concedido activa",
                           c2[0] is True and c2[1] is True))

            # caso 3: fin de turno con pestana oculta -> notifica con la respuesta
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:70, kind:'assistant',"
                     "         text:'Hecho, todo verde.', streaming:false});"
                     " window.__n=null;"
                     " Object.defineProperty(document,'hidden',"
                     "{value:true,configurable:true});"
                     " maybeNotify()")
            await asyncio.sleep(0.05)
            n3 = await js("window.__n && [window.__n.t, window.__n.o.body]")
            print("  oculta: %s" % (n3,))
            checks += [
                ("con la pestana oculta, notifica al terminar", bool(n3)),
                ("titulo fijo 'pi remote'", bool(n3) and n3[0] == "pi remote"),
                ("el cuerpo es la respuesta del agente",
                 bool(n3) and "Hecho, todo verde" in n3[1]),
            ]

            # caso 3b: respuesta larga -> se recorta con elipsis
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:71, kind:'assistant',"
                     "         text:'x'.repeat(500), streaming:false});"
                     " window.__n=null; maybeNotify()")
            await asyncio.sleep(0.05)
            n3b = await js("window.__n && window.__n.o.body")
            print("  larga: len=%s" % (n3b and len(n3b)))
            checks.append(("la respuesta larga se recorta",
                           bool(n3b) and len(n3b) <= 221
                           and n3b.endswith("…")))

            # caso 4: pestana visible -> NO notifica
            await js("window.__n=null;"
                     " Object.defineProperty(document,'hidden',"
                     "{value:false,configurable:true});"
                     " maybeNotify()")
            await asyncio.sleep(0.05)
            n4 = await js("window.__n")
            print("  visible: %s" % n4)
            checks.append(("con la pestana visible no molesta", n4 is None))

            # caso 5: permiso denegado -> dialog, no activa
            await js("document.querySelector('#modal').classList.remove('open');"
                     " setNotify(false); window.Notification.permission='denied';"
                     " window.__ok=null;"
                     " requestNotify(function(ok){window.__ok=ok;})")
            await asyncio.sleep(0.05)
            c5 = await js("[document.querySelector('#modal')"
                          ".classList.contains('open'), window.__ok, notify]")
            print("  denegado: abierto=%s ok=%s notify=%s"
                  % (c5[0], c5[1], c5[2]))
            checks += [
                ("denegado abre dialog", c5[0] is True),
                ("y no activa", c5[1] is False and c5[2] is False),
            ]

            # caso 6: la card existe en Functions
            await js("document.querySelector('#modal').classList.remove('open');"
                     " paintSheet('functions')")
            await asyncio.sleep(0.05)
            labels = await js("[...document.querySelectorAll('#sheetBody .fcard "
                              ".flbl')].map(function(n){return n.textContent;})")
            print("  cards: %s" % labels)
            checks.append(("hay card de notificaciones en Functions",
                           "Notificaciones" in labels))

            checks.append(("sin errores de consola", not p.problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
