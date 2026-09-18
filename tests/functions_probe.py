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

            # la raiz del menu ofrece 'pi remote settings', con Funciones dentro
            await js("paintSheet('root')")
            has = await js("[...document.querySelectorAll('#sheetBody .pick')]"
                           ".some(b => /pi remote/.test(b.textContent))")
            checks.append(("la raiz de ajustes lista 'pi remote settings'",
                           has is True))
            await js("(async()=>{[...document.querySelectorAll('#sheetBody .pick')]"
                     ".find(b => /pi remote/.test(b.textContent)).click();"
                     " await new Promise(r=>setTimeout(r,400));})()")
            has2 = await js("[...document.querySelectorAll('#sheetBody .pick')]"
                            ".some(b => /Funciones/.test(b.textContent))")
            checks.append(("'pi remote settings' lista 'Funciones'", has2 is True))

            # la pagina Functions: una card con el switch, encendido por defecto
            await js("paintSheet('functions')")
            card = await js("(() => {"
                " const c = document.querySelector('#sheetBody .fcard');"
                " if(!c) return null;"
                " const sw = c.querySelector('.sw');"
                " return [!!sw, sw.getAttribute('role'),"
                "  sw.getAttribute('aria-checked'),"
                "  c.querySelector('.flbl').textContent,"
                "  !c.querySelector('.fsub'),"
                "  getComputedStyle(sw).borderRadius];})()")
            print("  card:", json.dumps(card, ensure_ascii=True))
            checks += [
                ("hay una card con el switch", card and card[0] is True),
                ("es un switch accesible (role=switch)", card and card[1] == "switch"),
                ("encendido por defecto", card and card[2] == "true"),
                ("rotulado 'Mostrar razonamiento'",
                 card and card[3] == "Mostrar razonamiento"),
                ("sin subtitulo: solo el titulo", card and card[4] is True),
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

            # --- la card Movement: ahora un interruptor (on=fundido, off=directo)
            await js("paintSheet('functions')")
            find = ("[...document.querySelectorAll('#sheetBody .fcard')]"
                    ".find(c => { const l = c.querySelector('.flbl');"
                    " return l && l.textContent === 'Generación suave'; })")
            mv = await js("(() => { const c = %s; if(!c) return null;"
                          " const sw = c.querySelector('.sw');"
                          " return [!!sw, sw && sw.getAttribute('aria-checked'),"
                          "  document.documentElement.classList"
                          ".contains('motion-fade')];})()" % find)
            print("  movement:", json.dumps(mv, ensure_ascii=True))
            checks += [
                ("la card 'Generación suave' es un interruptor",
                 mv and mv[0] is True),
                ("por defecto encendido (fundido)", mv and mv[1] == "true"),
                ("arranca en modo fundido", mv and mv[2] is True),
            ]

            # apagar -> directo: cambia la clase raiz y se recuerda
            await js("%s.querySelector('.sw').click()" % find)
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

            # encender de nuevo -> vuelve a fundido
            await js("%s.querySelector('.sw').click()" % find)
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
