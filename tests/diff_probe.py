"""Diferencias de una edicion, y el aviso cuando no hay token."""
import asyncio
import json

import websockets

from harness import Bridge, FakeProject, Page, PORT, report

WS = "ws://127.0.0.1:%d/ws" % PORT

# una edicion y una llamada normal, pintadas en el cliente
SEED = r"""
feed.innerHTML = ""; nodes.clear();
render({id:1, kind:"tool", name:"edit", status:"done",
        args:{path:"app/main.py"}, added:3, removed:2,
        lines:["@@ -1,3 +1,4 @@",
               " def run():",
               "-    print('viejo')",
               "-    return 1",
               "+    print('nuevo')",
               "+    log('ok')",
               "+    return 0"]});
render({id:2, kind:"tool", name:"bash", status:"done",
        args:{command:"ls -la"}, output:"total 48"});
[document.querySelectorAll('.tally').length,
 (document.querySelector('.tally .plus')||{}).textContent,
 (document.querySelector('.tally .minus')||{}).textContent,
 document.querySelectorAll('.diff .add').length,
 document.querySelectorAll('.diff .del').length,
 document.querySelectorAll('.diff .at').length,
 (document.querySelector('.tool .nm')||{}).textContent]
"""

COLOURS = """(() => {
  const add = getComputedStyle(document.querySelector('.diff .add'));
  const del = getComputedStyle(document.querySelector('.diff .del'));
  return [add.color, add.backgroundColor !== 'rgba(0, 0, 0, 0)',
          del.color, del.backgroundColor !== 'rgba(0, 0, 0, 0)'];
})()"""


async def from_the_bridge():
    """El puente calcula el diff solo, a partir de los argumentos."""
    with FakeProject("diff") as proj, Bridge():
        async with websockets.connect(WS) as ws:
            await ws.recv()
            await ws.send(json.dumps({"type": "open_project",
                                      "path": proj.path}))
            edit = None
            for _ in range(60):
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 6))
                except asyncio.TimeoutError:
                    break
                items = ([m["item"]] if m["type"] == "item"
                         else m.get("items", []))
                for it in items:
                    if it.get("kind") == "tool" and it.get("name") == "edit":
                        edit = it
                if edit:
                    break
    print("  del puente: +%s -%s  %d lineas"
          % (edit and edit.get("added"), edit and edit.get("removed"),
             len(edit.get("lines") or []) if edit else 0))
    return [
        ("el puente cuenta las lineas de una edicion",
         bool(edit) and edit.get("added") == 3 and edit.get("removed") == 2),
        ("y manda el diff", bool(edit) and len(edit.get("lines") or []) >= 6),
    ]


async def with_token():
    """Con token, el aviso no debe salir."""
    with Bridge(extra={"PI_WEB_TOKEN": "secreto"}):
        async with websockets.connect(WS + "?token=secreto") as ws:
            snap = json.loads(await ws.recv())
        print("  con token: open=%r" % snap["state"].get("open"))
        return [("con token no se avisa", snap["state"].get("open") is False)]


async def main():
    checks = await from_the_bridge()

    with Bridge():
        async with Page(port=9311) as p:
            await p.go()
            await p.js("setLang('es')")
            r = await p.js(SEED)
            print("  filas con cuenta=%s  %s / %s" % (r[0], r[1], r[2]))
            print("  lineas: +%s -%s contexto=%s   titulo=%r"
                  % (r[3], r[4], r[5], r[6]))
            col = await p.js(COLOURS)
            print("  colores: anadido=%s fondo=%s | quitado=%s fondo=%s"
                  % tuple(col))
            warn = await p.js("[$('#warnbar').hidden,"
                              " $('#warnbar').textContent.trim().slice(0,30),"
                              " !!document.querySelector('#warnbar svg')]")
            print("  aviso sin token: oculto=%s %r" % (warn[0], warn[1]))
            await p.go()                       # segunda visita
            again = await p.js("[$('#warnbar').hidden,"
                               " localStorage.getItem('pi.warned')]")
            print("  al volver: oculto=%s marca=%r" % tuple(again))

            await p.js(SEED)        # la recarga de antes vacio el feed

            # el spinner mientras llega el historial
            await p.js("spinner(true)")
            await asyncio.sleep(0.2)
            spin_on = await p.js("[!!$('#spin'),"
                                 " getComputedStyle($('#spin')).animationName]")
            await p.js("spinner(false)")
            await asyncio.sleep(0.1)
            spin_mid = await p.js("$('#spin') ? [Number(getComputedStyle("
                                  "$('#spin')).opacity),"
                                  " $('#spin').classList.contains('out')]"
                                  " : [null, null]")
            await asyncio.sleep(0.4)
            spin_off = await p.js("!!$('#spin')")
            print("  spinner: aparece=%s gira=%r | al irse opacidad=%s"
                  " | queda=%s" % (spin_on[0], spin_on[1], spin_mid[0],
                                   spin_off))

            # los desplegables de las herramientas
            det = """(() => {
              const d = document.querySelector('.tool');
              const b = d.querySelector(':scope > .diff, :scope > pre');
              return [d.open, getComputedStyle(b).height,
                      d.classList.contains('moving')];
            })()"""
            before = await p.js(det)
            await p.js("document.querySelector('.tool > summary').click()")
            await asyncio.sleep(0.09)
            mid = await p.js(det)
            await asyncio.sleep(0.4)
            after = await p.js(det)
            print("  desplegable: %s %s -> a 90ms %s %s -> %s %s"
                  % (before[0], before[1], mid[0], mid[1],
                     after[0], after[1]))

            checks += [
                ("el spinner sale y gira",
                 spin_on[0] is True and spin_on[1] == "turn"),
                ("y se va desvaneciendo",
                 spin_mid[1] is True and 0 <= (spin_mid[0] or 0) < 1),
                ("sin dejar rastro", spin_off is False),
                ("el desplegable se cierra animando",
                 before[0] is True and mid[2] is True
                 and mid[1] not in ("0px", before[1])),
                ("y acaba cerrado", after[0] is False),
                ("solo la edicion lleva cuenta", r[0] == 1),
                ("suma en verde y resta en rojo",
                 r[1] == "+3" and r[2] == "-2"),
                ("las lineas salen coloreadas",
                 r[3] == 3 and r[4] == 2 and r[5] == 1),
                ("la fila muestra el fichero, no el json",
                 "app/main.py" in (r[6] or "")),
                ("verde y rojo con su fondo",
                 col[1] is True and col[3] is True and col[0] != col[2]),
                ("sin token se avisa en pantalla",
                 warn[0] is False and warn[2] is True and warn[1] != ""),
                ("y solo la primera vez",
                 again[0] is True and again[1] == "1"),
            ]

    checks += await with_token()
    return report(checks)


raise SystemExit(asyncio.run(main()))
