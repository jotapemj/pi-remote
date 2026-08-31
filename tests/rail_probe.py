"""Acordeon de proyectos, sesiones anidadas y pulsacion larga.

Cuenta sesiones, nunca imprime sus etiquetas. Sin prompts."""
import asyncio
import json

from harness import Bridge, FakeProject, Page, ROOT, URL, report

# dos proyectos de mentira: uno vacio y otro con sesiones creadas aqui
SEED = """
state = {running:false, waiting:false, alive:true, cwd:"",
  sessionName:null, model:null, thinking:null, context:null,
  queue:{steering:[],followUp:[]},
  recent:[{name:"vacio", path:%s}, {name:"con-sesiones", path:%s}]};
window.__sent = [];
ws.send = s => window.__sent.push(JSON.parse(s));
paint(); openRail();
"""

GROUP = """(() => {
  const g = document.querySelectorAll('.pgroup')[%d];
  const s = getComputedStyle(g.querySelector('.subs'));
  return [g.classList.contains('open'), s.gridTemplateRows,
          Number(s.opacity).toFixed(2),
          g.querySelectorAll('.sess').length,
          (g.querySelector('.subs .none') || {}).textContent || ""];
})()"""

HOLD = """(() => {
  const h = document.querySelectorAll('.pgroup')[%d].querySelector('.proj');
  h.dispatchEvent(new PointerEvent('pointerdown',
    {clientX: 20, clientY: 20, bubbles: true}));
})()"""

async def main():
    with FakeProject("vacio") as a, FakeProject("con-sesiones",
                                                sessions=3) as b:
        A, B = a.path, b.path
        with Bridge():
            async with Page(port=9306) as p:
                js, cmd = p.js, p.cmd
                await p.go()
                await js("setLang('es')")
                await js(SEED % (json.dumps(A), json.dumps(B)))
                await asyncio.sleep(0.4)

                checks = []
                cerrado = await js(GROUP % 0)
                print("  plegado      :", cerrado[:3], "filas", cerrado[3])
                checks.append(("empieza plegado",
                               cerrado[0] is False and cerrado[1] == "0px"))

                await js("toggleProj(%s)" % json.dumps(A))
                await asyncio.sleep(0.12)
                medio = await js(GROUP % 0)
                await asyncio.sleep(0.7)
                abierto = await js(GROUP % 0)
                print("  a 120ms      :", medio[:3])
                print("  desplegado   :", abierto[:3], "filas", abierto[3],
                      "| aviso", repr(abierto[4]))
                checks.append(("despliega animando",
                               medio[1] not in ("0px", abierto[1])))
                checks.append(("queda abierto",
                               abierto[0] is True and abierto[1] != "0px"))
                checks.append(("sin sesiones lo dice y ofrece crear",
                               abierto[3] == 1 and abierto[4] != ""))

                # el segundo proyecto si tiene sesiones: solo las cuento
                await js("toggleProj(%s)" % json.dumps(B))
                await asyncio.sleep(0.9)
                otro = await js(GROUP % 1)
                uno = await js(GROUP % 0)
                print("  otro proyecto: filas", otro[3], "(1 crear + sesiones)")
                checks.append(("lista las sesiones de esa carpeta", otro[3] >= 2))
                checks.append(("solo uno desplegado a la vez", uno[0] is False))

                # volver a tocarlo lo pliega
                await js("toggleProj(%s)" % json.dumps(B))
                await asyncio.sleep(0.6)
                plegado = await js(GROUP % 1)
                checks.append(("volver a tocar pliega", plegado[0] is False))

                # abrir una sesion manda el path de la sesion
                await js("window.__sent = []")
                await js("document.querySelectorAll('.pgroup')[1]"
                         ".querySelectorAll('.sess')[1].click()")
                await asyncio.sleep(0.3)
                sent = await js("window.__sent")
                print("  al tocar una sesion:", json.dumps(sent)[:96])
                checks.append(("abre proyecto y sesion",
                               bool(sent) and sent[0]["type"] == "open_project"
                               and bool(sent[0].get("session"))))

                # pulsacion larga
                await js("closeModal()")
                await js(HOLD % 0)
                await asyncio.sleep(0.75)
                menu = await js("[$('#modal').classList.contains('open'),"
                                " $('#modalTitle').textContent,"
                                " [...document.querySelectorAll('#modalBody .mrow')]"
                                ".map(b=>b.textContent)]")
                print("  pulsacion larga:", menu[1], menu[2])
                checks.append(("la pulsacion larga abre el dialogo",
                               menu[0] is True))
                checks.append(("con dos opciones", len(menu[2]) == 2))

                return report(checks)

raise SystemExit(asyncio.run(main()))
