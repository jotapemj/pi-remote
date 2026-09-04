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

            # la caja de un comando: bloque COMANDO (completo, sin recorte)
            # y bloque SALIDA con su texto; las que fallan tambien nacen cerradas
            longcmd = ("Get-ChildItem -Recurse -File | Where-Object "
                       "{ $_.FullName -notmatch 'node_modules' } | "
                       "Format-Table -AutoSize")
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:10, kind:'tool', name:'bash',"
                     " status:'done', args:{command:%s},"
                     " output:'total 48 ficheros'});"
                     " render({id:11, kind:'tool', name:'bash',"
                     " status:'error', args:{command:'rm /x'},"
                     " output:'rm: no existe'})" % json.dumps(longcmd))
            await asyncio.sleep(0.25)
            con = await js("(() => {"
                           " const ok = document.querySelector"
                           "('.tool[data-s=done]');"
                           " const err = document.querySelector"
                           "('.tool[data-s=error]');"
                           " ok.open = true;"
                           " const cc = ok.querySelector('.ccmd');"
                           " return [!!ok.querySelector('.cout .ch'),"
                           "  ok.querySelector('.cout pre').textContent.trim(),"
                           "  err.open,"
                           "  err.querySelector('.cout pre').textContent"
                           ".includes('no existe'),"
                           "  cc ? cc.querySelector('pre').textContent : '',"
                           "  cc ? getComputedStyle(cc.querySelector('pre'))"
                           ".whiteSpace : '',"
                           "  getComputedStyle(ok.querySelector('.cout'))"
                           ".borderTopWidth];})()")
            print("  caja: salida=%s texto=%r err_abierto=%s err_txt=%s"
                  % tuple(con[:4]))
            print("  comando: completo=%s wrap=%r divisoria=%r"
                  % (con[4] == longcmd, con[5], con[6]))
            checks += [
                ("la salida tiene cabecera y texto",
                 con[0] is True and "total 48" in con[1]),
                ("un comando que falla nace cerrado, con su error dentro",
                 con[2] is False and con[3] is True),
                ("el bloque COMANDO trae el comando entero sin recortar",
                 con[4] == longcmd),
                ("y ajusta linea en vez de desbordar", con[5] == "pre-wrap"),
                ("con una divisoria antes de la salida",
                 con[6] not in ("0px", "", None)),
            ]

            # --- una sola no se agrupa
            await js(SOLO)
            await asyncio.sleep(0.25)
            solo = await js("[!!document.querySelector('.toolgroup'),"
                            " document.querySelectorAll('.tool').length]")
            print("  una sola: grupo=%s tools=%s" % (solo[0], solo[1]))
            checks.append(("una sola herramienta no se agrupa",
                           solo[0] is False and solo[1] == 1))

            # --- razonamiento oculto intercalado no rompe el tramo
            # (Qwen mete thinking entre tool calls; oculto seguia en el DOM
            # y dejaba cada tool suelta)
            await js("setThinking(false)")   # hide-think
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:1, kind:'user', text:'lee cosas'});"
                     " for(let i=0;i<4;i++){"
                     "  render({id:100+i, kind:'thinking', text:'mmm',"
                     "          streaming:false});"
                     "  render({id:200+i, kind:'tool', name:'read',"
                     "          status:'done', args:{path:'x'}, output:'ok'});}"
                     " render({id:9, kind:'assistant', streaming:false,"
                     "         text:'Ya.'}); paint()")
            await asyncio.sleep(0.3)
            mix = await js("(() => {"
                           " const g = document.querySelector('.toolgroup');"
                           " const loose = [...document.querySelectorAll("
                           "'.tool')].filter(t => !t.closest('.toolgroup'))"
                           ".length;"
                           " return g ? [g.querySelectorAll('.gbody .tool')"
                           ".length, g.querySelector('.gn').textContent,"
                           "  g.querySelectorAll('.gbody .think-turn').length,"
                           "  loose] : null;})()")
            await js("setThinking(true)")
            print("  thinking oculto: %s" % (mix,))
            checks += [
                ("el thinking intercalado no rompe el tramo",
                 mix is not None and mix[0] == 4 and mix[3] == 0),
                ("el rotulo cuenta solo las herramientas",
                 mix is not None and "4 comandos" in mix[1]),
                ("el razonamiento se absorbe en el grupo",
                 mix is not None and mix[2] == 4),
            ]

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
