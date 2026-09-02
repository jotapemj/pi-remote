"""El razonamiento del modelo se muestra como un desplegable 'Penso Xs',
cerrado por defecto. Se cubre el render (vivo, cerrado, historial), el
toggle, que un delta de pensamiento NO esconde la palabra rotatoria, y el
turno real de fake_pi que trae thinking_start/delta/end. Sin agente real.
"""
import asyncio
import json

from harness import Bridge, FakeProject, Page, report


async def main():
    checks = []
    with Bridge(), FakeProject() as proj:
        async with Page(port=9319) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")

            # --- vivo: streaming, plegado, 'Pensando...'
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:1, kind:'thinking',"
                     " text:'razonando en voz baja', streaming:true}); paint();")
            await asyncio.sleep(0.15)
            live = await js("(() => {"
                " const d = document.querySelector('details.think');"
                " if(!d) return null;"
                " return [d.open,"
                "  d.querySelector('.tlabel').textContent,"
                "  d.querySelector('.tbody').textContent.trim(),"
                "  getComputedStyle(d.querySelector('.tbody')).fontStyle];})()")
            print("  vivo:", json.dumps(live, ensure_ascii=True))
            checks += [
                ("se genera un <details.think>", live is not None),
                ("plegado por defecto", live and live[0] is False),
                ("mientras razona dice Pensando", live and "Pensando" in live[1]),
                ("el cuerpo lleva el texto del razonamiento",
                 live and "razonando" in live[2]),
                ("el cuerpo va en italica", live and live[3] == "italic"),
            ]

            # --- etiqueta al estilo Claude: 'Penso durante N segundos/minutos'
            async def label(secs):
                await js("feed.innerHTML=''; nodes.clear();"
                         " render({id:9, kind:'thinking', text:'x',"
                         " streaming:false, secs:%d}); paint();" % secs)
                await asyncio.sleep(0.05)
                return await js("document.querySelector('.think .tlabel')"
                                ".textContent")
            l3 = await label(3)
            l1 = await label(1)
            lmin = await label(180)
            print("  etiquetas: 3s=%s 1s=%s 180s=%s"
                  % (json.dumps(l3, ensure_ascii=True),
                     json.dumps(l1, ensure_ascii=True),
                     json.dumps(lmin, ensure_ascii=True)))
            checks += [
                ("plural: 'Penso durante 3 segundos'",
                 "durante 3 segundos" in (l3 or "") and "Pens" in (l3 or "")),
                ("singular: '1 segundo', sin la s de mas",
                 "1 segundo" in (l1 or "") and "1 segundos" not in (l1 or "")),
                ("pasa a minutos: 'durante 3 minutos'",
                 "durante 3 minutos" in (lmin or "")),
            ]

            # el toggle lo abre
            await js("document.querySelector('.think > summary').click()")
            await asyncio.sleep(0.1)
            opened = await js("document.querySelector('.think').open")
            checks.append(("el desplegable se abre al pulsarlo", opened is True))

            # --- historial: sin duracion -> 'Razonamiento'
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:3, kind:'thinking', text:'del disco',"
                     " streaming:false}); paint();")
            await asyncio.sleep(0.1)
            hist = await js("document.querySelector('.think .tlabel').textContent")
            print("  historial:", json.dumps(hist, ensure_ascii=True))
            checks.append(("sin duracion dice 'Razonamiento'",
                           "Razonamiento" in (hist or "")))

            # --- un delta de pensamiento NO esconde la palabra rotatoria
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:4, kind:'thinking', text:'a',"
                     " streaming:true}); paint();"
                     " $('#readout').classList.add('thinking');"
                     " ws.onmessage({data: JSON.stringify("
                     "{type:'delta', id:4, delta:'bc'})});")
            await asyncio.sleep(0.1)
            noword = await js("[$('#readout').classList.contains('thinking'),"
                              " document.querySelector('.think .tbody')"
                              ".textContent.trim()]")
            print("  delta:", json.dumps(noword, ensure_ascii=True))
            checks += [
                ("el delta crece el cuerpo del pensamiento",
                 noword[1] == "abc"),
                ("y NO apaga la palabra rotatoria", noword[0] is True),
            ]

            # --- turno real de fake_pi: piensa y luego responde
            await js("feed.innerHTML=''; nodes.clear()")
            await js("send({type:'open_project', path:%s})"
                     % json.dumps(proj.path))
            await asyncio.sleep(1.5)
            await js("send({type:'prompt', message:'think please'})")
            end = asyncio.get_event_loop().time() + 8
            started = False
            while asyncio.get_event_loop().time() < end:
                busy = await js("state.running")
                if busy:
                    started = True
                if started and not busy:
                    break
                await asyncio.sleep(0.2)
            # el ultimo bloque de pensamiento es el del turno en vivo
            real = await js("(() => {"
                " const ts = [...document.querySelectorAll('details.think')];"
                " const d = ts[ts.length - 1];"
                " const a = [...document.querySelectorAll('.said')]"
                ".map(s => s.textContent).join(' ');"
                " return d ? [d.querySelector('.tlabel').textContent,"
                "  d.querySelector('.tbody').textContent.trim(), a] : null;"
                "})()")
            print("  turno real:", json.dumps(real, ensure_ascii=True))
            checks += [
                ("el turno real produce un bloque de pensamiento",
                 real is not None),
                ("con el texto que razono dentro",
                 real and "decido" in real[1]),
                ("rotulado como Penso/Pensando", real and "Pens" in real[0]),
                ("y la respuesta sale aparte, como texto",
                 real and "respuesta clara" in real[2]),
            ]

            checks.append(("sin errores de consola", not p.problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
