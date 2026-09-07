"""Diferencias de una edicion, y el aviso cuando no hay token."""
import asyncio
import json

import websockets

from harness import Bridge, FakeProject, Page, PORT, report, WS_URL

WS = WS_URL

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


def gist_checks():
    """El puente saca el comando de los argumentos de la herramienta."""
    import pi_web_bridge as B
    cases = [
        ({"command": "rm -rf ./build"}, "rm -rf ./build"),
        ({"language": "shell", "code": "cd /x && ls"}, "cd /x && ls"),
        ({"path": "app/main.py", "edits": []}, "app/main.py"),
        (None, ""),
    ]
    got = [B.tool_gist(a) for a, _ in cases]
    for (a, want), g in zip(cases, got):
        print("  %-42r -> %r" % (a, g))
    return [("saca el comando de los argumentos",
             got == [w for _, w in cases])]


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
    """Con token se ejecuta; sin el, el puente pasa a solo lectura."""
    out = []
    with Bridge(extra={"PI_WEB_TOKEN": "secreto"}):
        bare = WS.split("?")[0]
        async with websockets.connect(bare + "?token=secreto") as ws:
            snap = json.loads(await ws.recv())
        print("  con token: readOnly=%r" % snap["state"].get("readOnly"))
        out.append(("con token no se avisa",
                    snap["state"].get("readOnly") is False))
        for bad in ("", "?token=otro"):
            try:
                async with websockets.connect(bare + bad):
                    ok = False
            except Exception:
                ok = True
            print("  token %-14r rechazado: %s" % (bad or "(ninguno)", ok))
            out.append(("sin el token bueno no se entra (%s)"
                        % (bad or "vacio"), ok))
    return out


async def read_only():
    """Sin token el puente mira, pero no toca. Y la pagina lo dice."""
    with Bridge(extra={"PI_WEB_TOKEN": "off"}):
        async with websockets.connect(WS.split("?")[0]) as ws:
            snap = json.loads(await ws.recv())
            await ws.send(json.dumps({"type": "prompt", "message": "hola"}))
            await ws.send(json.dumps({"type": "bash", "command": "whoami"}))
            await asyncio.sleep(1.0)
            await ws.send(json.dumps({"type": "get_state"}))
            saw, notes = [], []
            end = asyncio.get_event_loop().time() + 4
            while asyncio.get_event_loop().time() < end:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(),
                                                          timeout=1.5))
                except asyncio.TimeoutError:
                    break
                saw.append(m.get("type"))
                it = m.get("item") or {}
                if it.get("kind") == "note":
                    notes.append(it.get("key"))
                if it.get("kind") == "user":
                    notes.append("USER")
        print("  sin token: readOnly=%r" % snap["state"].get("readOnly"))
        print("  lo que contesto: %s" % notes)
        out = [
            ("sin token el estado lo dice",
             snap["state"].get("readOnly") is True),
            ("el prompt no llega al agente", "USER" not in notes),
            ("y se rechaza diciendo por que",
             notes.count("read_only") == 2),
        ]

        async with Page(port=9312) as p:
            await p.go()
            await asyncio.sleep(0.5)
            ui = await p.js("(() => {"
                            " box.value = '/'; box.dispatchEvent("
                            "new Event('input'));"
                            " const all = [...document.querySelectorAll("
                            "'.cmd')];"
                            " const bash = all.find(b =>"
                            " b.textContent.includes('/bash'));"
                            " const stats = all.find(b =>"
                            " b.textContent.includes('/stats'));"
                            " return [$('#warnbar').hidden,"
                            "  bash ? bash.disabled : null,"
                            "  stats ? stats.disabled : null,"
                            "  !box.isContentEditable,"
                            " $('#send').disabled];})()")
            print("  la pagina: aviso oculto=%s /bash=%s /stats=%s"
                  " caja=%s enviar=%s" % tuple(ui))
            out += [
                ("la pagina avisa", ui[0] is False),
                ("los comandos que actuan salen apagados", ui[1] is True),
                ("los de mirar siguen vivos", ui[2] is False),
                ("y no se puede ni escribir",
                 ui[3] is True and ui[4] is True),
            ]
    return out


async def main():
    checks = gist_checks()
    checks += await from_the_bridge()

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
            await p.js(SEED)        # la recarga de antes vacio el feed

            # el spinner mientras llega el historial
            await p.js("spinner(true)")
            await asyncio.sleep(0.35)
            spin_on = await p.js("[!!$('#spin'),"
                                 " getComputedStyle($('#spin path')).animationName,"
                                 " $('#spin').querySelectorAll('path').length,"
                                 " document.body.classList.contains('loading'),"
                                 " getComputedStyle($('#feed')).visibility,"
                                 " getComputedStyle($('.entry')).opacity,"
                                 " getComputedStyle($('#spin')).position]")
            await p.js("spinner(false)")
            await asyncio.sleep(0.1)
            spin_mid = await p.js("$('#spin') ? [Number(getComputedStyle("
                                  "$('#spin')).opacity),"
                                  " $('#spin').classList.contains('out'),"
                                  " getComputedStyle($('#spin path')).fillOpacity]"
                                  " : [null, null, null]")
            await asyncio.sleep(0.4)
            spin_off = await p.js("[!!$('#spin'),"
                                  " getComputedStyle($('.entry')).opacity,"
                                  " getComputedStyle($('#feed')).visibility]")
            print("  spinner: aparece=%s dibuja=%r letras=%s oculto=%s | al irse"
                  " opacidad=%s relleno=%s | queda=%s panel=%s feed=%s"
                  % (spin_on[0], spin_on[1], spin_on[2], spin_on[3:5],
                     spin_mid[0], spin_mid[2], spin_off[0], spin_off[1],
                     spin_off[2]))

            # los desplegables de las herramientas
            det = """(() => {
              const d = document.querySelector('.tool');
              const b = d.querySelector(':scope > .tbody, :scope > .diff, :scope > pre');
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
                ("el spinner dibuja el titulo letra a letra",
                 spin_on[0] is True and spin_on[1] == "d1, f1"
                 and spin_on[2] == 8),
                ("al llegar el chat salta al texto completo",
                 spin_mid[2] == "1"),
                ("mientras carga solo se ve la animacion, a pantalla completa",
                 spin_on[3] is True and spin_on[4] == "hidden"
                 and spin_on[5] == "0" and spin_on[6] == "fixed"),
                ("al llegar el chat vuelve el panel",
                 spin_off[1] == "1" and spin_off[2] == "visible"),
                ("y se va desvaneciendo",
                 spin_mid[1] is True and 0 <= (spin_mid[0] or 0) < 1),
                ("sin dejar rastro", spin_off[0] is False),
                ("el edit terminado nace plegado", before[0] is False),
                ("el desplegable se abre animando",
                 mid[2] is True and mid[1].endswith("px")
                 and mid[1] != "0px"),
                ("y acaba abierto", after[0] is True),
                ("solo la edicion lleva cuenta", r[0] == 1),
                ("suma en verde y resta en rojo",
                 r[1] == "+3" and r[2] == "-2"),
                ("las lineas salen coloreadas",
                 r[3] == 3 and r[4] == 2 and r[5] == 1),
                ("la fila muestra el fichero, no el json",
                 "app/main.py" in (r[6] or "")),
                ("verde y rojo con su fondo",
                 col[1] is True and col[3] is True and col[0] != col[2]),
            ]

    checks += await with_token()
    checks += await read_only()
    return report(checks)


raise SystemExit(asyncio.run(main()))
