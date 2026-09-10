"""Resumen al parar: con la funcion activa, parar un turno pensante manda
{abort, summary}. El puente ABORTA el turno (lo interrumpe de verdad; no lo
deja terminar) y, al asentarse, pide el resumen con un prompt aparte. El boton
queda en aro (summing, guiado por state.summarizing del puente) desde el abort
hasta que llega el resumen, que es texto normal de asistente: confirmacion fija
+ "estaba" + lo que hacia. Apagada, parar es un abort normal, sin resumen.
Se mide extremo a extremo contra fake_pi.
"""
import asyncio
import json

from harness import Bridge, FakeProject, Page, report


async def until(p, expr, timeout=8.0, step=0.1):
    for _ in range(int(timeout / step)):
        if await p.js(expr):
            return True
        await asyncio.sleep(step)
    return False


async def think_start(p):
    """Arranca un turno pensante (fake_pi: 'stopme') y espera a que piense."""
    await p.js("feed.innerHTML=''; nodes.clear();"
               " send({type:'prompt', message:'stopme'})")
    run = await until(p, "state.running === true")
    think = await until(p, "!!document.querySelector('.think')")
    return run and think


async def main():
    checks = []
    with Bridge(), FakeProject() as proj:
        async with Page(port=9331) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")
            await js("send({type:'open_project', path:%s})"
                     % json.dumps(proj.path))
            await asyncio.sleep(1.5)

            # --- OFF: parar sin la funcion -> abort, ningun resumen ---
            off_ok = await think_start(p)
            await js("stopsum = false; $('#send').click()")   # abort normal
            await until(p, "state.running === false")
            await asyncio.sleep(0.3)
            off_sum = await js("[...document.querySelectorAll('.said')]"
                               ".some(e => e.textContent.includes('Estaba'))")
            print("  OFF: pensó=%s resumen=%s" % (off_ok, off_sum))
            checks += [
                ("el turno pensante arranca", off_ok),
                ("apagado, parar no genera resumen", off_sum is False),
            ]

            # --- ON: parar con la funcion -> abort + resumen aparte ---
            on_ok = await think_start(p)
            before = await js("document.querySelectorAll('.blk-you').length")
            await js("stopsum = true; $('#send').click()")
            # el aro llega tras el round-trip: el puente marca state.summarizing
            ring = await until(p, "$('#send').classList.contains('summing')",
                               timeout=3)
            got = await until(p, "[...document.querySelectorAll('.said')]"
                              ".some(e => e.textContent.includes('Estaba'))")
            ring_off = await until(p, "!$('#send')"
                                   ".classList.contains('summing')", timeout=5)
            await asyncio.sleep(0.2)
            # la generacion original se corto: nunca llego su 'Listo.'
            finished = await js("[...document.querySelectorAll('.said')]"
                                ".some(e => e.textContent.trim() === 'Listo.')")
            special = await js("document.querySelectorAll('.said.stopsum')"
                               ".length")
            txt = await js("[...document.querySelectorAll('.said')]"
                           ".map(e => e.textContent)"
                           ".filter(t => t.includes('Estaba')).pop() || null")
            after = await js("document.querySelectorAll('.blk-you').length")
            print("  ON: pensó=%s aro=%s->%s cortó=%s especial=%s users %s->%s"
                  " texto=%r" % (on_ok, ring, ring_off, not finished, special,
                                 before, after, txt))
            checks += [
                ("el turno pensante arranca (on)", on_ok),
                ("el boton entra en aro al parar", ring),
                ("la generacion se interrumpe (no termina)", not finished),
                ("aparece la respuesta al parar", got),
                ("la respuesta trae confirmacion + estaba",
                 bool(txt) and "Vale, paro" in txt
                 and "Estaba revisando" in txt),
                ("es texto normal de asistente, sin estilo especial",
                 special == 0),
                ("el aro se quita al terminar", ring_off),
                ("el resumen no anade burbuja de usuario", after == before),
            ]

            checks.append(("sin errores de consola", not p.problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
