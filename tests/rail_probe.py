"""Barra lateral: chats recientes arriba, proyectos debajo, acordeon de
sesiones anidadas, clic derecho y boton de tres puntos.

Cuenta sesiones, nunca imprime sus etiquetas. Sin prompts."""
import asyncio
import json
import os
import time

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
  h.dispatchEvent(new MouseEvent('contextmenu',
    {bubbles: true, cancelable: true}));
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
            # una sesion cuyo CONTENIDO contiene "zorro raro" pero cuyo
            # nombre no: la busqueda por nombre no la debe ver
            extra = b.sess_dir / "2026-01-09_zorro.jsonl"
            extra.write_text(
                '{"type": "session", "name": "sesion sin marca"}\n'
                '{"type": "message", "message": {"role": "user", '
                '"content": "hablemos del zorro raro"}}\n',
                encoding="utf-8")
            fut = time.time() + 5
            os.utime(extra, (fut, fut))   # que sea la mas nueva

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
                    if n == 4:
                        break
                    await asyncio.sleep(0.2)
                lay = await js("""(() => {
                  // orden en el DOM, robusto al anidamiento (la lista va en
                  // un scroll interno, con la papelera en un pie fijo)
                  const before = (a, b) => !!(a.compareDocumentPosition(b)
                    & Node.DOCUMENT_POSITION_FOLLOWING);
                  return [before($('#addBtn'), $('#chats')),
                          before($('#searchBtn'), $('#chats')),
                          before($('#chats'), $('#recents')),
                          !$('#chatHead').hidden, !$('#projHead').hidden];
                })()""")
                print("  disposicion: botones<chats<proyectos", lay)
                checks += [
                    ("los botones permanecen arriba",
                     lay[0] and lay[1]),
                    ("recientes debajo, proyectos al final",
                     n == 4 and lay[2] and lay[3] and lay[4]),
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

                # ---- rebautizado: recientes adopta el nombre nuevo ----
                # La sesion mas nueva cambia su etiqueta en disco (una
                # session_info al final + mtime) y la pagina recibe un state
                # con otro sessionName: #chats tiene que volver a pedir.
                newest = max(b.sess_dir.glob("*.jsonl"),
                             key=lambda f: f.stat().st_mtime)
                with open(newest, "a", encoding="utf-8") as fh:
                    fh.write('{"type": "session_info", '
                             '"name": "renombrada"}\n')
                fut2 = time.time() + 10
                os.utime(newest, (fut2, fut2))
                await js("state.sessionName = 'nueva'; paint()")
                ren = False
                for _ in range(30):
                    ren = "renombrada" in await js(
                        "document.querySelector('#chats').textContent")
                    if ren:
                        break
                    await asyncio.sleep(0.3)
                checks.append(("recientes adopta el nombre tras un rebautizado",
                               ren is True))

                # ---- vista de busqueda: pantalla completa sobre el rail ----
                await js("openSearch()")
                await asyncio.sleep(0.6)
                s0 = await js("""(() => {
                  const v = $('#searchView');
                  return [v.classList.contains('on'),
                          $('#rail').classList.contains('on'),
                          $('#searchInput').placeholder,
                          $('#searchList').querySelectorAll('.srow').length,
                          !!v.querySelector('.shead')];
                })()""")
                print("  busqueda     :", s0)
                checks += [
                    ("la busqueda abre y el rail se cierra",
                     s0[0] is True and s0[1] is False),
                    ("el hint dice buscar conversaciones",
                     s0[2] == "Buscar conversaciones"),
                    ("vacia lista todas las sesiones", s0[3] >= 4),
                    ("sin header de recientes en la vista",
                     s0[4] is False),
                ]

                # X sin texto: no hace nada; la flecha izquierda cierra
                await js("$('#searchX').click()")
                await asyncio.sleep(0.4)
                stay = await js("$('#searchView').classList.contains('on')")
                checks.append(("la X sin texto no cierra la vista",
                               stay is True))
                await js("$('#searchBack').click()")
                await asyncio.sleep(0.4)
                closed = await js("$('#searchView').classList.contains('on')")
                checks.append(("la flecha izquierda cierra la vista",
                               closed is False))

                await js("openSearch()")
                await asyncio.sleep(0.6)
                await js("$('#searchInput').value='prueba 2';"
                         " $('#searchInput')"
                         ".dispatchEvent(new Event('input'))")
                await asyncio.sleep(1.0)     # debounce + fetch
                r1 = await js("""(() => {
                  const rows = [...$('#searchList').querySelectorAll('.srow')];
                  return [rows.length, rows.map(r=>r.textContent)];
                })()""")
                checks.append(("la consulta filtra por nombre de sesion",
                               r1[0] == 1 and "prueba 2" in r1[1][0]))

                await js("$('#searchInput').value='zorro';"
                         " $('#searchInput')"
                         ".dispatchEvent(new Event('input'))")
                await asyncio.sleep(1.0)
                z = await js("$('#searchList').querySelectorAll('.srow').length")
                checks.append(("el contenido no cuenta, solo el nombre",
                               z == 0))

                await js("$('#searchX').click()")
                await asyncio.sleep(1.0)     # borra y vuelve a listar
                r2 = await js("""(() => [$('#searchInput').value,
                  $('#searchList').querySelectorAll('.srow').length])()""")
                checks.append(("la X con texto borra el texto",
                               r2[0] == "" and r2[1] >= 4))

                await js("$('#searchInput').value='prueba 2';"
                         " $('#searchInput')"
                         ".dispatchEvent(new Event('input'))")
                await asyncio.sleep(1.0)
                await js("window.__sent.length = 0;"
                         " $('#searchList').querySelector('.srow').click()")
                sent2 = await js("""(() => [window.__sent,
                  $('#searchView').classList.contains('on')])()""")
                checks += [
                    ("tocar un resultado abre la sesion",
                     len(sent2[0]) == 1
                     and sent2[0][0]["type"] == "open_project"
                     and bool(sent2[0][0].get("session"))),
                    ("y cierra la vista", sent2[1] is False),
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

                # clic derecho en la carpeta: popup flotante, no dialog
                await js(HOLD % 0)
                await asyncio.sleep(0.75)
                menu = await js("[!!document.querySelector('.ctxpop'),"
                                " [...document.querySelectorAll('.ctxrow')]"
                                ".map(b=>b.textContent),"
                                " document.querySelector('.ctxpop')?.style.left]")
                print("  clic derecho:", menu[1])
                checks.append(("el clic derecho abre el popup flotante",
                               menu[0] is True and len(menu[1]) == 2
                               and menu[2] not in (None, "")))
                await js("closeCtxPop()")

                # tres puntos en la carpeta y en una sesion
                dots = await js("""(() => {
                  const d = document.querySelectorAll('.pgroup')[0]
                    .querySelector('.proj .dotsb');
                  d.click();
                  const m1 = !!document.querySelector('.ctxpop');
                  closeCtxPop();
                  const s = document.querySelectorAll('.pgroup')[1]
                    .querySelector('.sess .dotsb');
                  s.click();
                  const m2 = !!document.querySelector('.ctxpop');
                  closeCtxPop();
                  return [m1, m2];
                })()""")
                checks.append(("los tres puntos abren el popup (carpeta y sesion)",
                               dots[0] is True and dots[1] is True))

                # el popup se cierra con clic fuera y con Esc
                await js("document.querySelectorAll('.pgroup')[0]"
                        ".querySelector('.proj .dotsb').click()")
                await asyncio.sleep(0.3)
                abrio = await js("!!document.querySelector('.ctxpop.on')")
                await js("document.body"
                         ".dispatchEvent(new PointerEvent('pointerdown'))")
                await asyncio.sleep(0.3)
                checks.append(("clic fuera cierra el popup",
                               abrio and not await js(
                                   "!!document.querySelector('.ctxpop')")))
                await js("document.querySelectorAll('.pgroup')[0]"
                        ".querySelector('.proj .dotsb').click()")
                await asyncio.sleep(0.3)
                abrio = await js("!!document.querySelector('.ctxpop.on')")
                await js("window.dispatchEvent(new KeyboardEvent('keydown',"
                         " {key:'Escape'}))")
                await asyncio.sleep(0.3)
                checks.append(("Esc cierra el popup",
                               abrio and not await js(
                                   "!!document.querySelector('.ctxpop')")))

            # rail fino: solo en escritorio
            async with Page(port=9307, width=1280, height=800,
                            mobile=False) as d:
                dj = d.js
                await d.go()
                await dj("try{if(ws)ws.onmessage=null;}catch(e){}")
                await dj(SEED % (json.dumps(A), json.dumps(B)))
                await asyncio.sleep(0.4)
                op = await dj("[getComputedStyle($('#slimRail')).opacity,"
                              " getComputedStyle($('#railFull')).opacity]")
                checks.append(("desplegado: iconos ocultos, contenido a la vista",
                               op == ["0", "1"]))
                await dj("setFolded(true)")
                await asyncio.sleep(0.6)
                st = await dj("[Number($('#rail').getBoundingClientRect().width),"
                              " getComputedStyle($('#slimRail')).opacity,"
                              " getComputedStyle($('#railFull')).opacity,"
                              " document.querySelectorAll('#slimRail .slimb')"
                              ".length]")
                checks.append(("plegado: rail de 64 px con los iconos",
                               st[0] == 64 and st[1] == "1" and st[2] == "0"
                               and st[3] == 5))
                # el logo lleva el cubo de pi remote; el hover solo cambia
                # el icono, no despliega
                logo = await dj("[!!$('#slimLogo img'), !!$('#slimLogo .hov svg')]")
                checks.append(("el logo es el icono de pi remote",
                               logo == [True, True]))
                await dj("$('#slimLogo')"
                         ".dispatchEvent(new Event('mouseenter'))")
                await asyncio.sleep(0.5)
                checks.append(("el hover no despliega la barra",
                               await dj("document.body"
                                        ".classList.contains('folded')")
                               is True))
                await dj("$('#slimLogo').click()")
                await asyncio.sleep(0.5)
                checks.append(("el clic en el logo despliega de verdad",
                               await dj("!document.body"
                                        ".classList.contains('folded')")
                               is True))

                # el bocadillo lista las conversaciones del proyecto abierto
                await dj("setFolded(true)")
                await asyncio.sleep(0.4)
                await dj("state.cwd = %s" % json.dumps(B))
                await dj("$('#slimChat').click()")
                await asyncio.sleep(0.8)
                ch = await dj("[!!document.querySelector('.ctxpop'),"
                              " document.querySelectorAll('.ctxrow').length]")
                checks.append(("el bocadillo abre el popup con los chats",
                               ch[0] is True and ch[1] >= 1))
                await dj("closeCtxPop()")

                return report(checks)

raise SystemExit(asyncio.run(main()))
