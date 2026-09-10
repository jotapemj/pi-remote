"""Barra lateral: chats recientes arriba, proyectos debajo, acordeon de
sesiones anidadas y pulsacion larga.

Cuenta sesiones, nunca imprime sus etiquetas. Sin prompts."""
import asyncio
import json

import websockets

from harness import Bridge, FakeProject, Page, ROOT, URL, WS_URL, report

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
            # el puente tambien tiene que conocer los proyectos: /api/search
            # barre su propio estado, no el que pinta la pagina
            async with websockets.connect(WS_URL) as ctl:
                await ctl.recv()
                for P in (A, B):
                    await ctl.send(json.dumps(
                        {"type": "open_project", "path": P}))
                    for _ in range(60):
                        m = json.loads(await asyncio.wait_for(
                            ctl.recv(), 15))
                        if m["type"] == "state" and \
                                m["state"].get("cwd", "").lower() == P.lower():
                            break
            async with Page(port=9306) as p:
                js, cmd = p.js, p.cmd
                await p.go()
                await js("setLang('es')")
                await js(SEED % (json.dumps(A), json.dumps(B)))
                await asyncio.sleep(0.4)

                checks = []
                # ---- chats recientes: hasta cuatro, de mas a menos nuevo ----
                for _ in range(40):
                    n = await js("$('#chats').querySelectorAll('.sess').length")
                    if n == 3:
                        break
                    await asyncio.sleep(0.2)
                lay = await js("""(() => {
                  const r = el =>
                    [...document.querySelectorAll('#rail > *')].indexOf(el);
                  return [r($('#chats')) < r($('#recents')),
                          r($('#recents')) < r($('#addBtn')),
                          !$('#chatHead').hidden, !$('#projHead').hidden];
                })()""")
                print("  disposicion: chats<proyectos<anadir", lay)
                checks += [
                    ("los cuatro ultimos chats van arriba",
                     n == 3 and lay[2]),
                    ("proyectos debajo, anadir proyecto al final",
                     lay[0] and lay[1] and lay[3]),
                ]

                await js("window.__sent.length = 0; closeRail();"
                         "$('#chats').querySelector('.sess').click()")
                got = await js("[window.__sent,"
                               " $('#rail').classList.contains('on')]")
                sent = got[0]
                checks += [
                    ("tocar un chat abre su proyecto y sesion",
                     len(sent) == 1
                     and sent[0]["type"] == "open_project"
                     and bool(sent[0].get("session"))),
                    ("y cierra la barra", got[1] is False),
                ]

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

                # Al abrir la sesion, el puente manda `cleared` y con el
                # se tira la cache: pudo nacer una sesion. El desplegable
                # tiene que volver a pedirla, no quedarse en "cargando".
                await js("toggleProj(%s)" % json.dumps(B))
                await asyncio.sleep(0.9)
                antes = await js(GROUP % 1)
                await js("""
                  state.cwd = %s;
                  feed.innerHTML = ""; nodes.clear();
                  delete sessCache[state.cwd];
                  paint();
                """ % json.dumps(B))
                await asyncio.sleep(0.15)
                justo = await js(GROUP % 1)
                await asyncio.sleep(1.2)
                luego = await js(GROUP % 1)
                print("  tras abrir sesion: %s filas -> %s (%r) -> %s"
                      % (antes[3], justo[3], justo[4], luego[3]))
                checks += [
                    ("sigue desplegado tras abrir la sesion",
                     luego[0] is True),
                    ("y las sesiones vuelven solas",
                     luego[3] == antes[3] and luego[4] == ""),
                ]

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
