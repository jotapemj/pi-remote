"""Las herramientas seguidas se pliegan en 'Ejecutados N comandos'.

Se cubren los dos ordenes: herramientas y luego texto (inyectado en el
DOM), y el turno real de fake_pi. Y que una sola no se agrupa. Sin tocar
al agente de verdad.
"""
import asyncio
import json

from harness import Bridge, FakeProject, Page, report


INJECT = """
feed.innerHTML = ""; nodes.clear();
render({id:1, kind:"user", text:"haz tres cosas"});
render({id:2, kind:"tool", name:"bash", status:"done",
        args:{command:"ls"}, output:"a"});
render({id:3, kind:"tool", name:"edit", status:"done",
        args:{path:"x.py"}, output:"ok"});
render({id:4, kind:"tool", name:"bash", status:"done",
        args:{command:"cat x"}, output:"b"});
render({id:5, kind:"assistant", streaming:false, text:"Ya esta."});
paint();
"""

SOLO = """
feed.innerHTML = ""; nodes.clear();
render({id:1, kind:"tool", name:"bash", status:"done",
        args:{command:"ls"}, output:"a"});
render({id:2, kind:"assistant", streaming:false, text:"una sola"});
paint();
"""

STATE = """(() => {
  const g = document.querySelector('.toolgroup');
  if(!g) return null;
  return [g.classList.contains('collapsed'),
          g.querySelectorAll('.gbody .tool').length,
          g.querySelector('.gn').textContent,
          Math.round(g.querySelector('.gbody').getBoundingClientRect().height),
          !!g.querySelector('.ghead .i')];
})()"""


async def main():
    checks = []
    with Bridge(), FakeProject() as proj:
        async with Page(port=9315) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")

            # --- orden herramientas -> texto
            await js(INJECT)
            await asyncio.sleep(0.3)
            g = await js(STATE)
            singles = await js("document.querySelectorAll("
                               "'#feed > .turn > .tool').length")
            print("  inyectado: grupo=%s | sueltas fuera=%s" % (g, singles))
            checks += [
                ("tres seguidas se agrupan", g is not None and g[1] == 3),
                ("plegado por defecto y sin altura",
                 g[0] is True and g[3] == 0),
                ("con el rotulo del recuento", "3 comandos" in g[2]),
                ("y ninguna herramienta suelta fuera del grupo",
                 singles == 0),
            ]

            # las tareas van con sangria, para no mezclarse con la cabecera
            indent = await js("(() => {"
                              " const g = document.querySelector('.toolgroup');"
                              " const head = g.querySelector('.ghead')"
                              ".getBoundingClientRect();"
                              " const tool = g.querySelector('.gbody .tool')"
                              ".getBoundingClientRect();"
                              " return [Math.round(tool.left - head.left),"
                              " getComputedStyle(g.querySelector('.gbody'))"
                              ".paddingLeft];})()")
            print("  sangria: tarea a %s px, padding %s"
                  % (indent[0], indent[1]))
            checks.append(("las tareas quedan sangradas bajo la cabecera",
                           indent[0] >= 10))

            # desplegar por el encabezado
            await js("document.querySelector('.ghead').click()")
            await asyncio.sleep(0.35)
            opened = await js(STATE)
            print("  al abrir: colapsado=%s alto=%s" % (opened[0], opened[3]))
            checks += [
                ("el encabezado lo despliega",
                 opened[0] is False and opened[3] > 0),
            ]

            # --- una sola no se agrupa
            await js(SOLO)
            await asyncio.sleep(0.25)
            solo = await js("[!!document.querySelector('.toolgroup'),"
                            " document.querySelectorAll('.tool').length]")
            print("  una sola: grupo=%s tools=%s" % (solo[0], solo[1]))
            checks.append(("una sola herramienta no se agrupa",
                           solo[0] is False and solo[1] == 1))

            # --- turno real de fake_pi (dos tools, luego se cierra)
            await js("feed.innerHTML=''; nodes.clear()")
            await js("send({type:'open_project', path:%s})"
                     % json.dumps(proj.path))
            await asyncio.sleep(1.5)
            await js("send({type:'prompt', message:'hola'})")
            end = asyncio.get_event_loop().time() + 8
            live = None
            while asyncio.get_event_loop().time() < end:
                live = await js(STATE)
                busy = await js("state.running")
                if live and not busy:
                    break
                await asyncio.sleep(0.2)
            print("  turno real: grupo=%s" % (live,))
            checks.append(("un turno real agrupa sus dos comandos al acabar",
                           live is not None and live[1] == 2
                           and "2 comandos" in live[2]))
    return checks


raise SystemExit(report(asyncio.run(main())))
