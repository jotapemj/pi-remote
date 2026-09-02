"""Cabecera y compositor reorganizados:
  - titulo = solo la sesion, subtitulo = solo el directorio
  - modelo y razonamiento bajan a la linea cmeta del compositor
  - el boton de enviar vive dentro de la caja: oculto vacio, visible al
    escribir, y cuadrado de parar al trabajar
  - botones de la toolbar sin caja y mas grandes
  - el interruptor de Functions usa el acento (ambar)
  - el pensamiento no lleva boton de copiar
  - help no cierra el menu; Aceptar vuelve a el, con un solo blur
"""
import asyncio
import json

from harness import Bridge, Page, report


async def main():
    checks = []
    with Bridge():
        async with Page(port=9323) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")

            await js("""state = {running:false, waiting:false, alive:true,
              cwd:'C:/proyectos/demo', sessionName:'mi sesion',
              model:'Qwen3 14B', thinking:'high',
              context:null, queue:{steering:[],followUp:[]}, recent:[]};
              paint();""")
            await asyncio.sleep(0.4)
            head = await js("[$('#title').textContent,"
                            " $('#sub').textContent.trim(),"
                            " $('#cmeta').textContent.trim()]")
            print("  titulo=%r sub=%r cmeta=%r" % tuple(head))
            checks += [
                ("el titulo es solo el nombre de sesion",
                 head[0] == "mi sesion"),
                ("el subtitulo es solo el directorio", head[1] == "demo"),
                ("modelo y razonamiento van al compositor",
                 "Qwen3 14B" in head[2] and "high" in head[2]),
            ]

            # el boton de enviar: oculto con caja vacia
            v0 = await js("Number(getComputedStyle($('#send')).opacity)")
            await js("box.value='hola'; box.dispatchEvent(new Event('input'))")
            await asyncio.sleep(0.25)
            v1 = await js("[Number(getComputedStyle($('#send')).opacity),"
                          " $('#field').contains($('#send')),"
                          " getComputedStyle($('#send')).position]")
            print("  send: vacio opac=%s  escribiendo opac=%s dentro=%s pos=%s"
                  % (v0, v1[0], v1[1], v1[2]))
            checks += [
                ("enviar oculto con la caja vacia", v0 < 0.1),
                ("enviar aparece al escribir", v1[0] > 0.9),
                ("enviar vive dentro de la caja",
                 v1[1] is True and v1[2] == "absolute"),
            ]

            # al trabajar: parar visible aunque la caja este vacia
            await js("box.value=''; box.dispatchEvent(new Event('input'));"
                     " state.running=true; paint();")
            await asyncio.sleep(0.25)
            st = await js("[Number(getComputedStyle($('#send')).opacity),"
                          " $('#send').classList.contains('halting'),"
                          " $('#field').classList.contains('busy')]")
            print("  trabajando: send opac=%s halting=%s field.busy=%s"
                  % tuple(st))
            checks += [
                ("al trabajar, parar se ve con la caja vacia",
                 st[0] > 0.9 and st[1] is True),
                ("la caja deja hueco al boton mientras trabaja",
                 st[2] is True),
            ]
            await js("state.running=false; box.value=''; paint()")

            # botones de la toolbar: sin borde, icono grande
            tb = await js("(() => { const b = getComputedStyle($('#railBtn'));"
                          " const i = $('#railBtn').querySelector('.i');"
                          " return [b.borderTopWidth,"
                          "  i ? Math.round(parseFloat(getComputedStyle(i)"
                          ".width)) : 0];})()")
            print("  toolbar rail: borde=%s icono=%spx" % tuple(tb))
            checks += [
                ("los botones de la toolbar no llevan caja", tb[0] == "0px"),
                ("y el icono es mas grande", tb[1] >= 22),
            ]

            # el interruptor de Functions usa el acento (ambar)
            await js("paintSheet('functions')")
            await js("document.querySelector('#sheetBody .sw')"
                     ".setAttribute('aria-checked','true')")
            swon = await js("getComputedStyle(document.querySelector"
                            "('#sheetBody .sw')).backgroundColor")
            amber = await js("(() => { const d = document.createElement('div');"
                             " d.style.background='var(--amber)';"
                             " document.body.appendChild(d);"
                             " const c = getComputedStyle(d).backgroundColor;"
                             " d.remove(); return c; })()")
            print("  sw on bg=%s  ambar=%s" % (swon, amber))
            checks.append(("el interruptor encendido es del color acento",
                           swon == amber))

            # el pensamiento con code fence: sin boton de copiar visible
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:1, kind:'thinking', streaming:false, secs:3,"
                     " text:'miro esto:\\n```py\\nx=1\\n```\\nlisto'});"
                     " document.querySelector('.think').open=true; paint();")
            await asyncio.sleep(0.2)
            cp = await js("(() => { const c = document.querySelector"
                          "('.think .copyb');"
                          " return [document.querySelectorAll('.think pre')"
                          ".length, c ? getComputedStyle(c).display : 'none'];"
                          "})()")
            print("  think: pre=%s copyb display=%s" % tuple(cp))
            checks += [
                ("el pensamiento renderiza el bloque de codigo", cp[0] >= 1),
                ("pero sin boton de copiar", cp[1] == "none"),
            ]

            # help no cierra el menu; Aceptar vuelve a el, con un solo blur
            await js("menuSheet(); paintSheet('root')")
            await asyncio.sleep(0.15)
            await js("[...document.querySelectorAll('#sheetBody .pick')]"
                     ".find(b => /Ayuda/.test(b.textContent)).click()")
            await asyncio.sleep(0.2)
            hp = await js("[$('#sheet').classList.contains('open'),"
                          " $('#modal').classList.contains('open')]")
            await js("$('#modalOk').click()")
            await asyncio.sleep(0.2)
            af = await js("[$('#sheet').classList.contains('open'),"
                          " $('#modal').classList.contains('open')]")
            print("  help: abierto sheet=%s modal=%s -> tras Aceptar"
                  " sheet=%s modal=%s" % (hp[0], hp[1], af[0], af[1]))
            checks += [
                ("help abre el dialogo sin cerrar el menu",
                 hp[0] is True and hp[1] is True),
                ("Aceptar cierra el dialogo y vuelve al menu",
                 af[0] is True and af[1] is False),
            ]

            await p.cmd("Emulation.setDeviceMetricsOverride", width=1440,
                        height=900, deviceScaleFactor=1, mobile=False)
            await asyncio.sleep(0.3)

            # en escritorio el enviar mide igual que el circulo de comando
            await js("$('#sheet').classList.remove('open');"
                     " box.value='hola'; box.dispatchEvent(new Event('input'))")
            await asyncio.sleep(0.25)
            sz = await js("[Math.round($('#send').getBoundingClientRect().width),"
                          " Math.round($('#send').getBoundingClientRect().height)]")
            await js("box.value=''; box.dispatchEvent(new Event('input'))")
            await asyncio.sleep(0.2)
            slw = await js("Math.round($('#slashBtn')"
                           ".getBoundingClientRect().width)")
            print("  escritorio: send=%sx%s  slashb=%s" % (sz[0], sz[1], slw))
            checks.append(("en escritorio enviar mide igual que el comando",
                           sz[0] == slw and sz[1] == slw))

            # un solo blur: en escritorio la hoja difumina; el dialogo, no
            await js("menuSheet(); paintSheet('root')")
            await asyncio.sleep(0.15)
            await js("[...document.querySelectorAll('#sheetBody .pick')]"
                     ".find(b => /Ayuda/.test(b.textContent)).click()")
            await asyncio.sleep(0.25)
            bl = await js("[getComputedStyle($('#sheet')).backdropFilter,"
                          " getComputedStyle($('#modal')).backdropFilter]")
            print("  blur escritorio: hoja=%r dialogo=%r" % tuple(bl))
            checks += [
                ("la hoja difumina el fondo", "blur" in (bl[0] or "")),
                ("el dialogo sobre la hoja no dobla el blur",
                 bl[1] in ("none", "", None)),
            ]

            checks.append(("sin errores de consola", not p.problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
