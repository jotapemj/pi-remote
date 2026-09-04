"""Imagen que devuelve una herramienta (p.ej. `read` de un png): el puente
reenvia el ImageContent del tool result, y el cliente pinta una miniatura en
la caja de la herramienta que, al pulsarla, se abre a pantalla (lightbox).
Un mimeType no-imagen no se pinta. Sin agente real: fake_pi devuelve la imagen.
"""
import asyncio
import json
import re

import websockets

from harness import Bridge, FakeProject, Page, report, WS_URL

PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP8"
       "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


async def passthrough():
    """El puente saca la imagen del tool result y la cuelga del item."""
    tools = {}
    with FakeProject() as proj, Bridge():
        async with websockets.connect(WS_URL) as ws:
            await ws.recv()                       # snapshot
            await ws.send(json.dumps({"type": "open_project",
                                      "path": proj.path}))
            await asyncio.sleep(1.2)
            await ws.send(json.dumps({"type": "prompt", "message": "readimg"}))
            end = asyncio.get_event_loop().time() + 6
            while asyncio.get_event_loop().time() < end:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 2))
                except asyncio.TimeoutError:
                    break
                if m.get("type") == "item":
                    it = m["item"]
                    if it.get("kind") == "tool":
                        tools[it["id"]] = it
                elif m.get("type") == "patch" and m["id"] in tools:
                    tools[m["id"]].update(m["fields"])
    read = next((t for t in tools.values() if t.get("name") == "read"), None)
    imgs = (read or {}).get("images") or []
    print("  puente: tool=%s imgs=%s mime=%s"
          % (bool(read), len(imgs), imgs[0]["mimeType"] if imgs else None))
    return [
        ("el puente reenvia la imagen del tool result",
         read is not None and len(imgs) == 1),
        ("con su mimeType y datos",
         bool(imgs) and imgs[0]["mimeType"] == "image/png"
         and imgs[0]["data"] == PNG),
        ("y conserva el texto de la salida",
         bool(read) and "Read image file" in (read.get("output") or "")),
    ]


async def in_page():
    checks = []
    with Bridge():
        async with Page(port=9375) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")

            # una herramienta read con imagen -> miniatura en la caja
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:1, kind:'tool', name:'read', status:'done',"
                     " args:{path:'shot.png'},"
                     " output:'Read image file [image/png]',"
                     " images:[{type:'image', data:'%s',"
                     " mimeType:'image/png'}]});"
                     " document.querySelector('.tool').open = true" % PNG)
            await asyncio.sleep(0.1)
            th = await js("(() => {"
                          " const t = document.querySelector('.toolimgs .tim');"
                          " return [document.querySelectorAll('.toolimgs .tim')"
                          ".length, t ? t.src.startsWith("
                          "'data:image/png;base64,') : false,"
                          "  getComputedStyle(t).cursor];})()")
            print("  miniatura: n=%s dataURI=%s cursor=%s" % tuple(th))
            checks += [
                ("la caja de la herramienta pinta la miniatura",
                 th[0] == 1 and th[1] is True),
                ("con cursor de ampliar", "zoom" in (th[2] or "")),
            ]

            # al pulsarla, se abre el lightbox con esa imagen
            lb0 = await js("$('#lightbox').hidden")
            await js("document.querySelector('.toolimgs .tim').click()")
            await asyncio.sleep(0.1)
            lb = await js("[$('#lightbox').hidden,"
                          " $('#lightbox').classList.contains('open'),"
                          " $('#lightbox img').src.startsWith("
                          "'data:image/png;base64,')]")
            print("  lightbox: antes_oculto=%s -> oculto=%s open=%s img=%s"
                  % (lb0, lb[0], lb[1], lb[2]))
            checks += [
                ("empieza oculto", lb0 is True),
                ("al pulsar la miniatura se abre a pantalla",
                 lb[0] is False and lb[1] is True and lb[2] is True),
            ]

            # la imagen deja el gesto al JS (pinch-zoom manual)
            ta = await js("getComputedStyle($('#lightbox img')).touchAction")
            checks.append(("la imagen deja el gesto al JS (touch-action none)",
                           ta == "none"))

            # el boton X lo cierra (en movil, tocar fuera no cierra)
            xok = await js("!!$('#lbClose') && $('#lbClose').children.length > 0")
            await js("$('#lbClose').click()")
            await asyncio.sleep(0.25)
            closed = await js("$('#lightbox').hidden")
            print("  X existe=%s -> cierra=%s" % (xok, closed))
            checks += [
                ("hay boton X para cerrar", xok is True),
                ("la X cierra el lightbox", closed is True),
            ]

            # arrastrar abajo cierra, y al soltar la imagen NO salta al centro
            # (ese salto seco era el glitch): debe seguir desplazada abajo
            await js("document.querySelector('.toolimgs .tim').click()")
            await asyncio.sleep(0.1)
            # el inline es determinista (no depende del frame de la transicion):
            # tras soltar debe quedar translateY grande (desliza), no 0 (glitch)
            tr = await js("(() => {"
                          " const lb = $('#lightbox');"
                          " const mk = (x,y) => new Touch({identifier:1,"
                          "  target:lb, clientX:x, clientY:y});"
                          " const ev = (ty,t) => lb.dispatchEvent("
                          "  new TouchEvent(ty, {touches: ty==='touchend'?[]:[t],"
                          "  changedTouches:[t], bubbles:true, cancelable:true}));"
                          " ev('touchstart', mk(200,100));"
                          " ev('touchmove',  mk(200,320));"
                          " ev('touchend',   mk(200,320));"
                          " return lb.querySelector('img').style.transform;})()")
            m = re.search(r"translateY\((\d+(?:\.\d+)?)px\)", tr or "")
            ty = float(m.group(1)) if m else -1
            await asyncio.sleep(0.3)
            gone = await js("$('#lightbox').hidden")
            print("  swipe-down: transform=%r translateY=%s -> oculto=%s"
                  % (tr, ty, gone))
            checks += [
                ("al soltar la imagen desliza abajo, no salta al centro",
                 ty > 90),
                ("y el arrastre abajo cierra", gone is True),
            ]

            # un mimeType no-imagen no se pinta
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:2, kind:'tool', name:'read', status:'done',"
                     " args:{path:'x'}, output:'x',"
                     " images:[{type:'image', data:'AAAA',"
                     " mimeType:'text/html'}]});"
                     " document.querySelector('.tool').open = true")
            await asyncio.sleep(0.1)
            noimg = await js("document.querySelectorAll('.toolimgs .tim').length")
            print("  no-imagen: tim=%s" % noimg)
            checks.append(("un mimeType no-imagen no se pinta", noimg == 0))

            checks.append(("sin errores de consola", not p.problems))
    return checks


async def main():
    checks = await passthrough()
    checks += await in_page()
    return checks


raise SystemExit(report(asyncio.run(main())))
