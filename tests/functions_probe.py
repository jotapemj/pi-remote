"""Settings tiene una pagina 'Functions' con una card y un switch Material
'Show thinking'. Al apagarlo, los bloques de razonamiento se ocultan y el
gusto se recuerda en local. Sin tocar al agente de verdad.
"""
import asyncio
import json

from harness import Bridge, FakeProject, Page, report


async def main():
    checks = []
    with Bridge(), FakeProject():
        async with Page(port=9321) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")

            # la raiz del menu ofrece 'Funciones'
            await js("paintSheet('root')")
            has = await js("[...document.querySelectorAll('#sheetBody .pick')]"
                           ".some(b => /Funciones/.test(b.textContent))")
            checks.append(("la raiz de ajustes lista 'Funciones'", has is True))

            # la pagina Functions: una card con el switch, encendido por defecto
            await js("paintSheet('functions')")
            card = await js("(() => {"
                " const c = document.querySelector('#sheetBody .fcard');"
                " if(!c) return null;"
                " const sw = c.querySelector('.sw');"
                " return [!!sw, sw.getAttribute('role'),"
                "  sw.getAttribute('aria-checked'),"
                "  c.querySelector('.flbl').textContent,"
                "  (c.querySelector('.fsub').textContent||'').length > 0,"
                "  getComputedStyle(sw).borderRadius];})()")
            print("  card:", json.dumps(card, ensure_ascii=True))
            checks += [
                ("hay una card con el switch", card and card[0] is True),
                ("es un switch accesible (role=switch)", card and card[1] == "switch"),
                ("encendido por defecto", card and card[2] == "true"),
                ("rotulado 'Mostrar pensamiento'",
                 card and card[3] == "Mostrar pensamiento"),
                ("con un subtitulo que explica", card and card[4] is True),
                ("el pulgar es redondo (pista pildora)",
                 card and card[5] not in (None, "", "0px")),
            ]

            # un bloque de razonamiento en pantalla, de momento visible
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:1, kind:'thinking', text:'x',"
                     " streaming:false, secs:2}); paint();")
            vis = await js("getComputedStyle("
                           "document.querySelector('.think-turn')).display")

            # apagar el switch: se oculta y se recuerda
            await js("document.querySelector('#sheetBody .sw').click()")
            await asyncio.sleep(0.05)
            off = await js("[document.querySelector('#sheetBody .sw')"
                           ".getAttribute('aria-checked'),"
                           " document.documentElement.classList"
                           ".contains('hide-think'),"
                           " getComputedStyle(document.querySelector"
                           "('.think-turn')).display,"
                           " (()=>{try{return localStorage.getItem"
                           "('pi.showThinking')}catch(e){return null}})()]")
            print("  visible antes=%s  tras apagar=%s"
                  % (vis, json.dumps(off, ensure_ascii=True)))
            checks += [
                ("antes de tocar nada, el razonamiento se ve", vis != "none"),
                ("apagado: el switch queda en false", off[0] == "false"),
                ("apagado: el razonamiento se oculta", off[2] == "none"),
                ("apagado: se recuerda en local (0)", off[3] == "0"),
            ]

            # encender otra vez: vuelve a verse y se recuerda encendido
            await js("document.querySelector('#sheetBody .sw').click()")
            await asyncio.sleep(0.05)
            on = await js("[document.documentElement.classList"
                          ".contains('hide-think'),"
                          " getComputedStyle(document.querySelector"
                          "('.think-turn')).display,"
                          " (()=>{try{return localStorage.getItem"
                          "('pi.showThinking')}catch(e){return null}})()]")
            print("  tras encender:", json.dumps(on, ensure_ascii=True))
            checks += [
                ("encendido de nuevo: reaparece", on[0] is False
                 and on[1] != "none"),
                ("encendido: se recuerda en local (1)", on[2] == "1"),
            ]

            # --- la segunda card: Movement, con dos formas de mostrar el texto
            await js("paintSheet('functions')")
            mv = await js("(() => {"
                " const segs = document.querySelectorAll('#sheetBody .seg button');"
                " if(segs.length !== 2) return null;"
                " const lab = document.querySelectorAll('#sheetBody .fcard .flbl');"
                " return [segs.length,"
                "  [...lab].some(l => l.textContent === 'Movimiento'),"
                "  segs[0].textContent, segs[0].getAttribute('aria-pressed'),"
                "  segs[1].textContent, segs[1].getAttribute('aria-pressed'),"
                "  document.documentElement.classList.contains('motion-fade')];})()")
            print("  movement:", json.dumps(mv, ensure_ascii=True))
            checks += [
                ("hay un segmentado de dos formas", mv and mv[0] == 2),
                ("la card se llama 'Movimiento'", mv and mv[1] is True),
                ("por defecto 'Fundido' y esta activo",
                 mv and mv[2] == "Fundido" and mv[3] == "true"),
                ("la otra es 'Directo' y esta suelta",
                 mv and mv[4] == "Directo" and mv[5] == "false"),
                ("arranca en modo fundido", mv and mv[6] is True),
            ]

            # pasar a Directo: cambia la clase raiz y se recuerda
            await js("[...document.querySelectorAll('#sheetBody .seg button')]"
                     ".find(b => b.dataset.m === 'instant').click()")
            await asyncio.sleep(0.05)
            di = await js("[document.documentElement.classList"
                          ".contains('motion-instant'),"
                          " document.documentElement.classList"
                          ".contains('motion-fade'),"
                          " (()=>{try{return localStorage.getItem"
                          "('pi.motion')}catch(e){return null}})()]")
            print("  a directo:", json.dumps(di, ensure_ascii=True))
            checks += [
                ("directo: la raiz queda en motion-instant",
                 di[0] is True and di[1] is False),
                ("directo: se recuerda en local", di[2] == "instant"),
            ]

            # volver a Fundido
            await js("[...document.querySelectorAll('#sheetBody .seg button')]"
                     ".find(b => b.dataset.m === 'fade').click()")
            await asyncio.sleep(0.05)
            fa = await js("[document.documentElement.classList"
                          ".contains('motion-fade'),"
                          " (()=>{try{return localStorage.getItem"
                          "('pi.motion')}catch(e){return null}})()]")
            checks += [
                ("vuelve a fundido", fa[0] is True and fa[1] == "fade"),
            ]

            checks.append(("sin errores de consola", not p.problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
