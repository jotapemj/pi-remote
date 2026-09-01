"""Pantalla ancha: la barra de proyectos es una columna, no un cajon.

Se mide el reparto real en pixeles, el tirador, el plegado y la ventana de
ajustes. Y que en estrecho nada de eso se activa. Sin prompts.
"""
import asyncio
import json

from harness import Bridge, Page, report

SEED = """
state = {running:false, waiting:false, alive:true, cwd:%s,
  sessionName:"sesion", model:"Qwen3 14B", thinking:"off",
  context:{percent:41.2, tokens:54000, window:131072},
  queue:{steering:[],followUp:[]},
  recent:[{name:"uno", path:%s}, {name:"dos", path:"C:\\\\p\\\\dos"}]};
feed.innerHTML = ""; nodes.clear();
render({id:2, kind:"assistant", streaming:false, text:"una respuesta"});
paint();
"""

LAYOUT = """(() => {
  const cols = getComputedStyle(document.body).gridTemplateColumns;
  const rail = $('#rail').getBoundingClientRect();
  const stack = $('#stack').getBoundingClientRect();
  const wrap = document.querySelector('.wrap').getBoundingClientRect();
  const entry = document.querySelector('.entry').getBoundingClientRect();
  return {cols: cols,
          railIzq: Math.round(rail.left), railAncho: Math.round(rail.width),
          chatIzq: Math.round(stack.left), texto: Math.round(wrap.width),
          caja: Math.round(entry.width),
          grip: getComputedStyle($('#grip')).display,
          menu: getComputedStyle($('#railBtn')).display,
          plegar: getComputedStyle($('#foldBtn')).display};
})()"""


async def wide(p, js):
    checks = []
    await p.cmd("Emulation.setDeviceMetricsOverride", width=1440, height=860,
                deviceScaleFactor=1, mobile=False)
    await js("localStorage.removeItem('pi.rail');"
             " localStorage.removeItem('pi.fold');"
             " setRailWidth(292, true); setFolded(false)")
    await asyncio.sleep(0.35)
    a = await js(LAYOUT)
    print("  ancho   : %s" % a["cols"])
    print("            barra %spx en x=%s | chat en x=%s, texto %spx,"
          " caja %spx" % (a["railAncho"], a["railIzq"], a["chatIzq"],
                          a["texto"], a["caja"]))
    checks += [
        ("dos columnas, la barra primero",
         a["railIzq"] == 0 and a["chatIzq"] == a["railAncho"]),
        ("el texto no cruza la pantalla entera", a["texto"] == 760),
        ("y la caja se alinea con el", abs(a["caja"] - a["texto"]) <= 30),
        ("el tirador esta, el boton de menu no",
         a["grip"] == "block" and a["menu"] == "none"
         and a["plegar"] == "flex"),
    ]

    # arrastrar la linea divisoria
    await js("(() => { const g = $('#grip');"
             " const r = g.getBoundingClientRect();"
             " const at = x => ({clientX:x, clientY:400, pointerId:1,"
             "   bubbles:true});"
             " g.dispatchEvent(new PointerEvent('pointerdown', at(r.left+3)));"
             " g.dispatchEvent(new PointerEvent('pointermove', at(410)));"
             " g.dispatchEvent(new PointerEvent('pointerup', at(410)));})()")
    await asyncio.sleep(0.3)
    b = await js(LAYOUT)
    saved = await js("localStorage.getItem('pi.rail')")
    print("  tirando : barra %spx, guardado %r" % (b["railAncho"], saved))
    checks += [
        ("arrastrar ensancha la barra", b["railAncho"] > a["railAncho"]),
        ("y el ancho se recuerda", saved == str(b["railAncho"])),
    ]

    # los topes
    await js("setRailWidth(9000, false)")
    top = await js("$('#rail').getBoundingClientRect().width")
    await js("setRailWidth(10, false)")
    low = await js("$('#rail').getBoundingClientRect().width")
    print("  topes   : %s / %s" % (round(top), round(low)))
    checks.append(("no se puede estirar ni encoger sin limite",
                   top <= 480 and low >= 190))

    # plegar
    await js("setRailWidth(292, true); setFolded(true)")
    await asyncio.sleep(0.35)
    c = await js(LAYOUT)
    print("  plegado : %s | menu=%s" % (c["cols"], c["menu"]))
    checks += [
        ("plegar deja la barra sin sitio", c["railAncho"] == 0),
        ("y devuelve el boton de menu", c["menu"] != "none"),
        ("el chat ocupa todo", c["chatIzq"] == 0),
    ]
    await js("$('#railBtn').click()")
    await asyncio.sleep(0.35)
    d = await js(LAYOUT)
    print("  vuelta  : barra %spx" % d["railAncho"])
    checks.append(("el boton de menu la trae de vuelta", d["railAncho"] > 0))

    # los ajustes son una ventana, no una hoja
    await js("menuSheet(); turnTo('appearance', 1)")
    await asyncio.sleep(0.9)
    v = await js("(() => { const c = document.querySelector('.sheet .card');"
                 " const r = c.getBoundingClientRect();"
                 " const s = getComputedStyle($('#sheet'));"
                 " return [s.alignItems, s.backdropFilter,"
                 "  getComputedStyle(c).borderRadius,"
                 "  Math.round(r.top), Math.round(innerHeight - r.bottom),"
                 "  document.querySelectorAll('.fontb').length];})()")
    print("  ajustes : %s blur=%r radio=%s arriba=%s abajo=%s fuentes=%s"
          % tuple(v))
    checks += [
        ("los ajustes salen centrados", v[0] == "center"),
        ("con desenfoque detras", "blur" in (v[1] or "")),
        ("y las cuatro esquinas redondeadas",
         v[2].split()[0] == "16px" and len(set(v[2].split())) == 1),
        ("despegados de arriba y de abajo", v[3] > 40 and v[4] > 40),
        ("con las fuentes disponibles", v[5] == 3),
    ]

    # la fuente elegida se aplica y se guarda
    await js("document.querySelector('.fontb[data-f=serif]').click()")
    await asyncio.sleep(0.3)
    f = await js("[getComputedStyle(document.querySelector('.said'))"
                 ".fontFamily, localStorage.getItem('pi.font'),"
                 ' document.fonts.check(`16px "Source Serif 4"`),'
                 " document.querySelectorAll('.fontb.on').length]")
    print("  fuente  : %r guardada=%r cargada=%s marcadas=%s" % tuple(f))
    checks += [
        ("elegir fuente la aplica al transcripto",
         f[0].startswith('"Source Serif 4"') and f[1] == "serif"),
        ("y esa fuente se sirve desde el puente", f[2] is True),
        ("solo una queda marcada", f[3] == 1),
    ]
    await js("setFont('sans'); $('#sheet').classList.remove('open')")
    return checks


async def narrow(p, js):
    await p.cmd("Emulation.setDeviceMetricsOverride", width=412, height=880,
                deviceScaleFactor=2, mobile=True)
    await asyncio.sleep(0.35)
    n = await js("[getComputedStyle(document.body).display,"
                 " getComputedStyle($('#grip')).display,"
                 " getComputedStyle($('#railBtn')).display,"
                 " getComputedStyle($('#foldBtn')).display,"
                 " getComputedStyle($('#rail')).position,"
                 " getComputedStyle(document.querySelector('.sheet .card'))"
                 ".borderRadius]")
    print("  estrecho: body=%s grip=%s menu=%s plegar=%s rail=%s radio=%s"
          % tuple(n))
    return [
        ("en estrecho la barra sigue siendo un cajon",
         n[0] == "flex" and n[4] == "fixed"),
        ("sin tirador ni boton de plegar",
         n[1] == "none" and n[3] == "none"),
        ("y con el boton de menu de siempre", n[2] != "none"),
        ("los ajustes vuelven a subir desde abajo",
         n[5].startswith("12px 12px 0")),
    ]


async def main():
    with Bridge():
        async with Page(port=9313, width=1440, height=860,
                        mobile=False) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")
            await js(SEED % (json.dumps("C:\\p\\uno"),
                             json.dumps("C:\\p\\uno")))
            await asyncio.sleep(0.4)
            checks = await wide(p, js)
            checks += await narrow(p, js)
    return checks


raise SystemExit(report(asyncio.run(main())))
