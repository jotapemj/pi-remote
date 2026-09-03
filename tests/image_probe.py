"""Imagenes: el puente reenvia 'images' a pi (end-to-end contra fake_pi), y el
cliente las adjunta desde el popup, pinta miniatura con X, las manda en el
prompt y las muestra en la burbuja. Barra inferior con esquinas curvas.
"""
import asyncio
import json

import websockets

from harness import Bridge, FakeProject, Page, report, WS_URL

PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP8"
       "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

MAKE_FILE = """(() => {
  const b = Uint8Array.from(atob('%s'), c => c.charCodeAt(0));
  const f = new File([b], 'x.png', {type:'image/png'});
  const dt = new DataTransfer(); dt.items.add(f);
  imgInput.files = dt.files;
  imgInput.dispatchEvent(new Event('change'));
})()""" % PNG


async def passthrough():
    """El puente pasa 'images' a pi: fake_pi cuenta y responde 'Veo N'."""
    out = []
    with FakeProject() as proj, Bridge():
        async with websockets.connect(WS_URL) as ws:
            await ws.recv()  # snapshot
            await ws.send(json.dumps({"type": "open_project",
                                      "path": proj.path}))
            await asyncio.sleep(1.2)
            await ws.send(json.dumps({"type": "prompt", "message": "mira",
                "images": [{"type": "image", "data": PNG,
                            "mimeType": "image/png"}]}))
            user_imgs, said = None, ""
            end = asyncio.get_event_loop().time() + 5
            while asyncio.get_event_loop().time() < end:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 2))
                except asyncio.TimeoutError:
                    break
                it = m.get("item") or {}
                if it.get("kind") == "user":
                    user_imgs = it.get("images")
                if it.get("kind") == "assistant":
                    said += it.get("text", "")
                if m.get("type") == "delta":
                    said += m.get("delta", "")
    print("  puente: user.images=%s  respuesta=%r" % (bool(user_imgs), said))
    out += [
        ("el item de usuario lleva la imagen",
         bool(user_imgs) and len(user_imgs) == 1),
        ("el puente reenvia images a pi (ve 1 imagen)", "1 imagen" in said),
    ]
    return out


async def in_page():
    checks = []
    with Bridge():
        async with Page(port=9324) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")
            await js("state={running:false,waiting:false,alive:true,cwd:'C:/x',"
                     "sessionName:'s',model:'m',thinking:'x',context:null,"
                     "queue:{steering:[],followUp:[]},recent:[]}; paint()")

            # adjuntar (simulada) -> miniatura con X, enviar asoma
            await js(MAKE_FILE)
            await asyncio.sleep(0.3)
            th = await js("[document.querySelectorAll('#thumbs .thumb').length,"
                          " !$('#thumbs').hidden,"
                          " !!document.querySelector('#thumbs .thx svg'),"
                          " $('#field').classList.contains('hasimg'),"
                          " Number(getComputedStyle($('#send')).opacity)]")
            print("  miniatura: n=%s visible=%s X=%s hasimg=%s send=%s"
                  % tuple(th))
            checks += [
                ("adjuntar crea una miniatura", th[0] == 1 and th[1] is True),
                ("con una X para quitarla", th[2] is True),
                ("y el enviar asoma sin texto",
                 th[3] is True and th[4] > 0.9),
            ]

            # enviar: el payload lleva images; se limpian las miniaturas
            await js("window.__sent=[]; ws.send = s => window.__sent.push("
                     "JSON.parse(s));")
            await js("box.value='mira'; box.dispatchEvent(new Event('input'));"
                     " submit()")
            await asyncio.sleep(0.2)
            sent = await js("(() => { const m = window.__sent.find("
                            "x => x.type === 'prompt');"
                            " return m ? [m.message, (m.images||[]).length,"
                            "  (m.images||[])[0] && m.images[0].mimeType,"
                            "  !!((m.images||[])[0] && m.images[0].data)]"
                            " : null; })()")
            after = await js("[document.querySelectorAll('#thumbs .thumb')"
                             ".length, $('#field').classList.contains('hasimg')]")
            print("  enviado: %s  tras enviar miniaturas=%s" % (sent, after))
            checks += [
                ("el envio lleva message + images",
                 sent and sent[0] == "mira" and sent[1] == 1
                 and sent[2] == "image/png" and sent[3] is True),
                ("y limpia las miniaturas", after[0] == 0 and after[1] is False),
            ]

            # la miniatura entra animada, y al quitarla con la X sale animada
            await js(MAKE_FILE)
            await asyncio.sleep(0.3)
            enter = await js("(() => { const t = document.querySelector"
                             "('#thumbs .thumb'); const cs = getComputedStyle(t);"
                             " return [t.classList.contains('in'),"
                             "  cs.transitionDuration !== '0s'];})()")
            await js("document.querySelector('#thumbs .thx').click()")
            await asyncio.sleep(0.06)
            outc = await js("(() => { const t = document.querySelector"
                            "('#thumbs .thumb'); return t ? [t.classList"
                            ".contains('out'), Number(getComputedStyle(t)"
                            ".opacity) < 1] : [false, false];})()")
            await asyncio.sleep(0.3)
            gone = await js("[document.querySelectorAll('#thumbs .thumb').length,"
                            " $('#thumbs').hidden,"
                            " $('#field').classList.contains('hasimg')]")
            print("  quitar: entra=%s sale=%s -> quedan=%s hidden=%s hasimg=%s"
                  % (enter, outc, gone[0], gone[1], gone[2]))
            checks += [
                ("la miniatura entra animada",
                 enter[0] is True and enter[1] is True),
                ("y sale animada (clase out, opacidad bajando)",
                 outc[0] is True and outc[1] is True),
                ("al quitar la ultima vuelve a lo normal",
                 gone[0] == 0 and gone[1] is True and gone[2] is False),
            ]

            # la burbuja pinta la imagen; un mimeType no-imagen no se pinta
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:1, kind:'user', text:'mira',"
                     " images:[{type:'image', data:'%s', mimeType:'image/png'}]})"
                     % PNG)
            await asyncio.sleep(0.1)
            bub = await js("(() => { const i = document.querySelector("
                           "'.blk-you .uimgs img');"
                           " return [document.querySelectorAll("
                           "'.blk-you .uimgs img').length,"
                           " i ? i.src.startsWith('data:image/png;base64,')"
                           " : false];})()")
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:2, kind:'user', text:'x',"
                     " images:[{type:'image', data:'AAAA',"
                     " mimeType:'text/html'}]})")
            await asyncio.sleep(0.1)
            noimg = await js("document.querySelectorAll('.blk-you .uimgs img')"
                             ".length")
            print("  burbuja: imgs=%s dataURI=%s  no-imagen=%s"
                  % (bub[0], bub[1], noimg))
            checks += [
                ("la burbuja pinta la imagen", bub[0] == 1 and bub[1] is True),
                ("un mimeType no-imagen no se pinta", noimg == 0),
            ]

            # barra inferior con esquinas superiores curvas
            rad = await js("getComputedStyle($('#field').closest('footer'),"
                           "'::before').getPropertyValue("
                           "'border-top-left-radius')")
            print("  footer radio=%r" % rad)
            checks.append(("la barra inferior curva arriba",
                           rad not in ("0px", "", None)))

            checks.append(("sin errores de consola", not p.problems))
    return checks


async def main():
    checks = await passthrough()
    checks += await in_page()
    return checks


raise SystemExit(report(asyncio.run(main())))
