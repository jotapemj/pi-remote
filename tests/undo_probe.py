"""Deshacer envio: si se pulsa parar antes de que el modelo empiece a pensar
o responder, la burbuja se borra y el texto vuelve al compositor. Si ya
empezo a generar, parar NO borra el mensaje. Contra fake_pi, sin modelo.
"""
import asyncio
import json

from harness import Bridge, FakeProject, Page, report


async def main():
    checks = []
    with Bridge(), FakeProject() as proj:
        async with Page(port=9322) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")
            await js("send({type:'open_project', path:%s})"
                     % json.dumps(proj.path))
            await asyncio.sleep(1.2)

            # --- caso 1: parar en la ventana pre-generacion -> deshace
            # feed limpio: el historial cargado ya trae .said de antes
            await js("feed.innerHTML=''; nodes.clear();"
                     " box.value = 'slow undo test';"
                     " box.dispatchEvent(new Event('input'))")
            await js("$('#send').click()")            # enviar
            started = False
            for _ in range(50):                       # espera al arranque
                st = await js("[state.running,"
                              " !!feed.querySelector('.said'),"
                              " !!feed.querySelector('.think'),"
                              " $('#send').classList.contains('halting')]")
                if st[0] and st[3] and not st[1] and not st[2]:
                    started = True
                    break
                await asyncio.sleep(0.05)
            pre = await js("[[...feed.querySelectorAll('.blk-you')]"
                           ".some(b => /slow undo test/.test(b.textContent)),"
                           " box.value]")
            print("  pre-gen: arranco=%s burbuja=%s caja=%r"
                  % (started, pre[0], pre[1]))
            checks += [
                ("el turno arranca en la ventana pre-generacion",
                 started is True),
                ("la burbuja del envio esta en pantalla", pre[0] is True),
                ("el compositor quedo vacio al enviar", pre[1] == ""),
            ]

            await js("$('#send').click()")            # parar -> deshacer
            await asyncio.sleep(0.35)
            un = await js("[[...feed.querySelectorAll('.blk-you')]"
                          ".some(b => /slow undo test/.test(b.textContent)),"
                          " box.value,"
                          " !!feed.querySelector('.said'),"
                          " document.activeElement === box]")
            print("  deshecho:", json.dumps(un, ensure_ascii=True))
            checks += [
                ("la burbuja desaparece", un[0] is False),
                ("el texto vuelve al compositor", un[1] == "slow undo test"),
                ("el modelo no genero respuesta", un[2] is False),
                ("y el foco vuelve al compositor", un[3] is True),
            ]

            # --- caso 2: si ya genero, parar NO borra el mensaje
            await js("feed.innerHTML=''; nodes.clear();"
                     " box.value='responde ya';"
                     " box.dispatchEvent(new Event('input'))")
            await js("$('#send').click()")
            gen = False
            for _ in range(80):                       # espera a que responda
                if await js("(() => { const s = feed.querySelector('.said');"
                            " return !!s && s.textContent.trim() !== ''; })()"):
                    gen = True
                    break
                await asyncio.sleep(0.05)
            await js("$('#send').click()")            # parar ya generando
            await asyncio.sleep(0.35)
            keep = await js("[[...feed.querySelectorAll('.blk-you')]"
                            ".some(b => /responde ya/.test(b.textContent)),"
                            " box.value]")
            print("  ya generado:", json.dumps(keep, ensure_ascii=True))
            checks += [
                ("empezo a responder", gen is True),
                ("parar tras generar mantiene la burbuja", keep[0] is True),
                ("y no devuelve nada al compositor", keep[1] == ""),
            ]

            checks.append(("sin errores de consola", not p.problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
