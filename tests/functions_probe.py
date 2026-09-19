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

            # --- card "Animacion de generacion": ahora un picker de 3 modos
            await js("paintSheet('functions')")
            card = ("[...document.querySelectorAll('#sheetBody .pick')]"
                    ".find(b => /Animaci.n de generaci.n/.test(b.textContent))")
            pk = await js("(() => { const b = %s; if(!b) return null;"
                          " return [!!b, !!b.querySelector('.ch'),"
                          "  (b.querySelector('.pval')||{}).textContent||''];})()"
                          % card)
            print("  picker:", json.dumps(pk, ensure_ascii=True))
            checks += [
                ("la animacion es un picker (con chevron)",
                 bool(pk) and pk[0] is True and pk[1] is True),
                ("muestra el modo actual en gris (Smooth)",
                 bool(pk) and "Smooth" in (pk[2] or "")),
            ]

            # abrir la vista de modos
            await js("%s.click()" % card)
            await asyncio.sleep(0.4)               # goPage anima
            page = await js("(()=>{"
                " const rows=[...document.querySelectorAll('#sheetBody .mrow')];"
                " return {n:rows.length, labels:rows.map(x=>"
                "   x.querySelector('.txt span').textContent),"
                "  sel:rows.filter(x=>x.classList.contains('sel'))"
                "   .map(x=>x.querySelector('.txt span').textContent),"
                "  chk:rows.map(x=>Number(getComputedStyle("
                "   x.querySelector('.chkslot')).opacity))};})()")
            print("  genanim:", json.dumps(page, ensure_ascii=True))
            checks += [
                ("la vista lista los tres modos", page["n"] == 3),
                ("los modos son Default/Smooth/Block",
                 page["labels"] == ["Default", "Smooth", "Block"]),
                ("el modo actual (Smooth) sale marcado, solo uno",
                 page["sel"] == ["Smooth"]),
                ("el check del elegido se ve y los demas no",
                 page["chk"][1] == 1 and page["chk"][0] == 0
                 and page["chk"][2] == 0),
            ]

            # elegir Block: marca sin cerrar y persiste
            await js("[...document.querySelectorAll('#sheetBody .mrow')]"
                     ".find(x=>x.querySelector('.txt span').textContent==='Block')"
                     ".click()")
            await asyncio.sleep(0.1)
            bl = await js("[document.documentElement.classList"
                          ".contains('motion-block'),"
                          " (()=>{try{return localStorage.getItem"
                          "('pi.motion')}catch(e){return null}})(),"
                          " [...document.querySelectorAll('#sheetBody .mrow')]"
                          ".filter(x=>x.classList.contains('sel'))"
                          ".map(x=>x.querySelector('.txt span').textContent),"
                          " !!document.querySelector('#sheetBody .mrow')]")
            print("  block:", json.dumps(bl, ensure_ascii=True))
            checks += [
                ("Block fija la clase raiz motion-block", bl[0] is True),
                ("Block se recuerda en local", bl[1] == "block"),
                ("la marca pasa a Block, solo uno", bl[2] == ["Block"]),
                ("la vista sigue en los modos (sin navegar)", bl[3] is True),
            ]

            # elegir Default: sin animacion, persiste
            await js("[...document.querySelectorAll('#sheetBody .mrow')]"
                     ".find(x=>x.querySelector('.txt span').textContent==='Default')"
                     ".click()")
            await asyncio.sleep(0.1)
            df = await js("[document.documentElement.classList"
                          ".contains('motion-default'),"
                          " (()=>{try{return localStorage.getItem"
                          "('pi.motion')}catch(e){return null}})()]")
            checks += [
                ("Default fija motion-default y lo recuerda",
                 df[0] is True and df[1] == "default"),
            ]

            checks.append(("sin errores de consola", not p.problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
