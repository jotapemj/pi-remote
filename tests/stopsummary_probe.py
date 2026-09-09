"""Resumen al parar: con la funcion activa, parar un turno pensante manda
{abort, summary} y el puente redirige el turno con un steer (no lo mata); el
boton de enviar queda en aro (summing) hasta que el agente responde, y la
respuesta llega como texto normal de asistente: confirmacion fija + "estaba"
+ lo que hacia. Apagada, parar es un abort normal, sin resumen.
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
            off_sum = await js("document.querySelectorAll('.said.stopsum')"
                               ".length")
            print("  OFF: pensó=%s resúmenes=%s" % (off_ok, off_sum))
            checks += [
                ("el turno pensante arranca", off_ok),
                ("apagado, parar no genera resumen", off_sum == 0),
            ]

            # --- ON: parar con la funcion -> steer -> respuesta normal ---
            on_ok = await think_start(p)
            before = await js("document.querySelectorAll('.blk-you').length")
            await js("stopsum = true; $('#send').click()")    # pide el resumen
            ring = await js("$('#send').classList.contains('summing')")
            got = await until(p, "[...document.querySelectorAll('.said')]"
                              ".some(e => e.textContent.includes('Estaba'))")
            await until(p, "state.running === false")
            await asyncio.sleep(0.2)
            ring_off = await js("$('#send').classList.contains('summing')")
            special = await js("document.querySelectorAll('.said.stopsum')"
                               ".length")
            txt = await js("[...document.querySelectorAll('.said')]"
                           ".map(e => e.textContent)"
                           ".filter(t => t.includes('Estaba'))"
                           ".pop() || null")
            after = await js("document.querySelectorAll('.blk-you').length")
            print("  ON: pensó=%s aro=%s->%s especial=%s users %s->%s"
                  " texto=%r" % (on_ok, ring, ring_off, special,
                                 before, after, txt))
            checks += [
                ("el turno pensante arranca (on)", on_ok),
                ("el boton queda en aro mientras llega la respuesta", ring),
                ("aparece la respuesta al parar", got),
                ("la respuesta trae confirmacion + estaba",
                 bool(txt) and "Vale, paro" in txt
                 and "Estaba revisando" in txt),
                ("es texto normal de asistente, sin estilo especial",
                 special == 0),
                ("el aro se quita al terminar", ring_off is False),
                ("el steer no anade burbuja de usuario", after == before),
            ]

            checks.append(("sin errores de consola", not p.problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
