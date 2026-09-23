"""Camara del compositor: fila del menu '+', input con capture, downscale.

Solo tactil: en escritorio la fila no existe (abrira la webcam). El input
`capture="environment"` abre la camara por defecto del movil y el permiso lo
pide el navegador; aqui se mide la plomeria: visibilidad por puntero, que el
clic dispare el input, y el downscale de addImage (lado mayor >2048 → canvas
→ jpeg q0.85; PNG conserva alpha; imagen pequena viaja tal cual).
"""
import asyncio
import json

import websockets

from harness import Bridge, Page, report, WS_URL


async def desktop_checks(p, js):
    checks = []
    vis = await js("getComputedStyle(document.querySelector("
                   "'[data-act=camera]')).display")
    print("  escritorio: fila camara display=%r" % vis)
    checks.append(("en escritorio la fila de camara no se ve",
                   vis == "none"))
    return checks


async def mobile_checks(p, js):
    checks = []
    row = await js("[getComputedStyle(document.querySelector("
                   "'[data-act=camera]')).display,"
                   "document.querySelector('[data-act=camera] svg path')"
                   ".getAttribute('d').slice(0,12),"
                   "document.getElementById('camInput')"
                   ".getAttribute('capture'),"
                   "document.querySelector('[data-act=camera] span:last-child')"
                   ".textContent]")
    print("  movil: display=%r icono=%r capture=%r label=%r" % tuple(row))
    checks += [
        ("en tactil la fila de camara se ve", row[0] == "flex"),
        ("con el icono photo_camera", row[1] == "M9 2 7.17 4H"),
        ("el input pide la camara trasera por defecto",
         row[2] == "environment"),
        ("y el rotulo esta traducido", row[3] == "Cámara"),
    ]

    # el clic en la fila dispara el input (stub: sin abrir camara de verdad)
    fired = await js("(()=>{window.__cam=0;"
                     "const ci=document.getElementById('camInput');"
                     "ci.click=()=>{window.__cam++};"
                     "document.querySelector('[data-act=camera]').click();"
                     "return window.__cam})()")
    closed = await js("!plusMenu.classList.contains('open')")
    print("  clic: disparos=%s menu_cerrado=%s" % (fired, closed))
    checks += [
        ("pulsar la fila abre el input de camara", fired == 1),
        ("y cierra el menu", closed is True),
    ]
    return checks


async def downscale_checks(p, js):
    checks = []

    # foto grande (3000x2000 jpeg) → se reduce a lado mayor 2048
    big = await js("(()=>{const c=document.createElement('canvas');"
                   "c.width=3000;c.height=2000;"
                   "const g=c.getContext('2d');g.fillStyle='#f80';"
                   "g.fillRect(0,0,3000,2000);"
                   "return c.toDataURL('image/jpeg',0.9)})()")
    await js("(()=>{const u=\"%s\",c=u.indexOf(',');"
             "addImage({data:u.slice(c+1),mimeType:'image/jpeg',url:u})"
             "})()" % big)
    got = await js("(async()=>{for(let i=0;i<50&&!pendingImages.length;i++)"
                   "await new Promise(r=>setTimeout(r,50));"
                   "if(!pendingImages.length)return null;"
                   "const im=pendingImages[0];const img=new Image();"
                   "await new Promise(r=>{img.onload=r;img.src=im.url});"
                   "return [im.mimeType,img.naturalWidth,img.naturalHeight,"
                   "im.data.length]})()")
    print("  grande: %r (original %d chars)" % (got, len(big)))
    checks += [
        ("la foto grande se adjunta", got is not None),
        ("reescrita como jpeg", got and got[0] == "image/jpeg"),
        ("con el lado mayor en 2048",
         got and max(got[1], got[2]) == 2048),
        ("y mas ligera que el original",
         got and len(big) > 40000 and got[3] < len(big) * 0.75),
    ]

    # png grande con alpha → se reduce pero sigue siendo png
    png = await js("(()=>{const c=document.createElement('canvas');"
                   "c.width=2600;c.height=1800;"
                   "const g=c.getContext('2d');"
                   "g.fillStyle='rgba(0,128,255,.5)';"
                   "g.fillRect(0,0,2600,1800);return c.toDataURL()})()")
    await js("(()=>{const u=\"%s\",c=u.indexOf(',');"
             "addImage({data:u.slice(c+1),mimeType:'image/png',url:u})"
             "})()" % png)
    got2 = await js("(async()=>{for(let i=0;i<50;i++)"
                    "{if(pendingImages.length>=2)break;"
                    "await new Promise(r=>setTimeout(r,50))}"
                    "const im=pendingImages[1];const img=new Image();"
                    "await new Promise(r=>{img.onload=r;img.src=im.url});"
                    "return [im.mimeType,img.naturalWidth,img.naturalHeight]"
                    "})()")
    print("  png grande: %r" % (got2,))
    checks += [
        ("el PNG grande se reduce conservando el formato",
         got2 and got2[0] == "image/png" and max(got2[1], got2[2]) <= 2048),
    ]

    # imagen pequena → tal cual, sin reescribir
    small = await js("(()=>{const c=document.createElement('canvas');"
                     "c.width=100;c.height=80;"
                     "const g=c.getContext('2d');g.fillStyle='#0f0';"
                     "g.fillRect(0,0,100,80);return c.toDataURL()})()")
    await js("(()=>{const u=\"%s\",c=u.indexOf(',');"
             "addImage({data:u.slice(c+1),mimeType:'image/png',url:u})"
             "})()" % small)
    same = await js("(async()=>{for(let i=0;i<50;i++)"
                    "{if(pendingImages.length>=3)break;"
                    "await new Promise(r=>setTimeout(r,50))}"
                    "return pendingImages[2].url===\"%s\"})()" % small)
    print("  pequena: sin tocar=%s" % same)
    checks.append(("la imagen pequena viaja tal cual", same is True))

    # las miniaturas se pintaron y el prompt llevaria las tres
    n = await js("[document.querySelectorAll('.thumb').length,"
                 "pendingImages.length]")
    print("  miniaturas=%s adjuntos=%s" % tuple(n))
    checks.append(("cada adjunto deja su miniatura", n == [3, 3]))
    return checks


async def main():
    with Bridge():
        async with Page(port=9373, width=1440, height=860,
                        mobile=False) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")
            checks = await desktop_checks(p, js)
            # el headless no vuelca (pointer:coarse) con las metricas de
            # movil: se emula el puntero tactil en el script de arranque y se
            # recarga, como en un telefono real
            await p.cmd("Page.addScriptToEvaluateOnNewDocument", source=
                        "const __mm=window.matchMedia.bind(window);"
                        "window.matchMedia=q=>q==='(pointer:coarse)'?"
                        "{matches:true,addEventListener(){},addListener(){}}"
                        ":__mm(q)")
            await p.go()
            checks += await mobile_checks(p, js)
            checks += await downscale_checks(p, js)
            checks += await chat_checks(p, js)
    return checks


async def chat_checks(p, js):
    # lo que entra por camara debe verse en la burbuja del chat, no solo
    # en el compositor: prompt con imagen -> item user -> .uimgs en el DOM
    u = await js("(()=>{const c=document.createElement('canvas');"
                 "c.width=120;c.height=90;"
                 "const g=c.getContext('2d');g.fillStyle='#5af';"
                 "g.fillRect(0,0,120,90);return c.toDataURL()})()")
    c = u.index(",")
    img = {"type": "image", "data": u[c + 1:],
           "mimeType": u[5:c].split(";")[0]}
    async with websockets.connect(WS_URL, max_size=40 * 1024 * 1024) as ws:
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m.get("type") == "snapshot":
                break
        await ws.send(json.dumps({"type": "prompt", "message": "mira",
                                  "images": [img], "lang": "es"}))
        item = None
        for _ in range(60):
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m.get("type") == "item" and m["item"].get("kind") == "user":
                item = m["item"]
                break
    await asyncio.sleep(1.0)
    dom = await js("(()=>{const u=document.querySelector('.uimgs');"
                   "return u?u.querySelectorAll('img').length:-1})()")
    print("  chat: item=%s dom=%s" % (bool(item and item.get("images")), dom))
    return [
        ("el item user lleva la imagen", bool(item and item.get("images"))),
        ("y la burbuja del chat la pinta", dom == 1),
    ]


raise SystemExit(report(asyncio.run(main())))
