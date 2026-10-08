"""Menu del mensaje del usuario: clic derecho en escritorio, pulsacion larga en
tactil. Dos opciones: copiar el mensaje entero, o poner los cursores de
seleccion donde se pulso. Clic fuera lo quita. Solo el mensaje del usuario.
"""
import asyncio
import json

from harness import Bridge, FakeProject, Page, report

SEED = """
feed.innerHTML = ''; nodes.clear();
render({id:7, kind:'user', streaming:false,
        text:'ajusta el puente y revisa la barra', t:Date.now()});
render({id:8, kind:'assistant', streaming:false, text:'una respuesta'});
paint();
"""

# punto dentro de la primera palabra de mi mensaje
POINT = """(() => { const t = document.querySelector('.mine .utext');
  const r = t.getBoundingClientRect();
  return [Math.round(r.left + 4), Math.round(r.top + 6)]; })()"""

RIGHT = """(() => { const t = document.querySelector('%s .utext');
  const r = t.getBoundingClientRect();
  t.dispatchEvent(new MouseEvent('contextmenu', {bubbles:true, cancelable:true,
    clientX: r.left + 4, clientY: r.top + 6})); })()"""

ROWS = """(() => { const p = document.querySelector('.ctxpop');
  return p ? [...p.querySelectorAll('.ctxrow span')].map(s => s.textContent)
           : null; })()"""

# el portapapeles del navegador sin https no existe: se mide lo que se le pide
STUB = """(() => { window.__clip = null;
  Object.defineProperty(navigator, 'clipboard', {value: {
    writeText: t => { window.__clip = t; return Promise.resolve(); }},
    configurable: true}); })()"""

OUTSIDE = """document.body.dispatchEvent(new PointerEvent('pointerdown',
  {bubbles:true}))"""

SEL = """(() => { const s = getSelection();
  const t = document.querySelector('.mine .utext');
  const r = t.getBoundingClientRect();
  const out = {txt: s.toString(), sel: getComputedStyle(t).userSelect,
               inside: false};
  if(s.rangeCount){ const b = s.getRangeAt(0).getBoundingClientRect();
    out.inside = b.left >= r.left - 1 && b.right <= r.right + 1
                 && b.top >= r.top - 1; }
  return out; })()"""

LONG = """(() => { const t = document.querySelector('.mine .utext');
  const r = t.getBoundingClientRect();
  t.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true,
    pointerType:'touch', clientX: r.left + 4, clientY: r.top + 6}));
  return true; })()"""


async def main():
    checks = []
    with Bridge(), FakeProject() as proj:
        async with Page(port=9319, width=1280, height=860, mobile=False) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")
            await js(SEED)
            await asyncio.sleep(0.4)
            await js(STUB)

            # escritorio: clic derecho
            x, y = await js(POINT)
            await js(RIGHT % ".mine")
            await asyncio.sleep(0.25)
            rows = await js(ROWS)
            pop = await js("""(() => { const p = document.querySelector('.ctxpop');
              return p ? [Math.round(p.getBoundingClientRect().left),
                          Math.round(p.getBoundingClientRect().top)] : null; })()""")
            print("  clic derecho: %s | en %s (pulso %s,%s)" % (rows, pop, x, y))
            checks += [
                ("el menu sale con sus dos opciones",
                 rows == ["Copiar mensaje", "Seleccionar texto"]),
                ("y junto al puntero", pop and abs(pop[0] - (x + 2)) <= 2
                 and abs(pop[1] - (y + 2)) <= 2),
            ]
            # el icono: trazado de Symbols (viewBox 960) pintado a 18 px
            icon = await js("""(() => { const b = document.querySelectorAll('.ctxrow')[1];
              const s = b.querySelector('svg'), r = s.getBoundingClientRect();
              const pr = s.querySelector('path').getBBox();
              return {vb: s.getAttribute('viewBox'), w: Math.round(r.width),
                      h: Math.round(r.height),
                      paint: pr.width > 0 && pr.height > 0}; })()""")
            print("  icono     : %s" % icon)
            checks += [
                ("el icono de seleccionar es el de Symbols",
                 icon["vb"] == "0 -960 960 960"),
                ("y pinta a 17 px", icon["w"] == 17 and icon["h"] == 17
                 and icon["paint"]),
            ]

            # copiar: el texto entero, tal como lo ve el usuario
            await js("document.querySelector('.ctxrow').click()")
            await asyncio.sleep(0.3)
            clip = await js("window.__clip")
            print("  copiar    : %r" % clip)
            checks.append(("copiar manda el mensaje entero al portapapeles",
                           clip == "ajusta el puente y revisa la barra"))

            # clic fuera: se quita
            await js(OUTSIDE)
            await asyncio.sleep(0.25)
            left = await js(ROWS)
            print("  fuera     : %s" % left)
            checks.append(("clic fuera quita el menu", left is None))

            # seleccionar texto: cursores en el punto del pulso
            await js(RIGHT % ".mine")
            await asyncio.sleep(0.25)
            await js("document.querySelectorAll('.ctxrow')[1].click()")
            await asyncio.sleep(0.3)
            s = await js(SEL)
            print("  seleccion : %s" % s)
            checks += [
                ("seleccionar texto pone cursores en la palabra pulsada",
                 s and s["txt"] == "ajusta"),
                ("y los cursores caen dentro del mensaje", s and s["inside"]),
            ]

            # el mensaje del asistente no tiene este menu
            await js(OUTSIDE)
            await asyncio.sleep(0.2)
            await js(RIGHT % ".said")
            await asyncio.sleep(0.25)
            none = await js(ROWS)
            print("  asistente : %s" % none)
            checks.append(("el menu es solo de mis mensajes", none is None))

            # tactil: pulsacion larga. El headless no vuelca (pointer:coarse)
            # con las metricas de movil: se emula el puntero en el script de
            # arranque y se recarga, como en un telefono real (camera_probe)
            await p.cmd("Emulation.setTouchEmulationEnabled", enabled=True,
                        maxTouchPoints=1)
            await p.cmd("Emulation.setDeviceMetricsOverride", width=412,
                        height=880, deviceScaleFactor=2, mobile=True)
            await p.cmd("Page.addScriptToEvaluateOnNewDocument", source=
                        "const __mm=window.matchMedia.bind(window);"
                        "window.matchMedia=q=>q==='(pointer:coarse)'?"
                        "{matches:true,addEventListener(){},addListener(){}}"
                        ":__mm(q)")
            await p.go()
            await js("setLang('es')")
            await js(STUB)
            await js(SEED)
            await asyncio.sleep(0.4)
            before = await js("getComputedStyle(document.querySelector("
                              "'.mine .utext')).userSelect")
            await js(LONG)
            await asyncio.sleep(0.7)
            rows = await js(ROWS)
            print("  pulso     : %s | seleccionable antes=%s" % (rows, before))
            checks += [
                ("en tactil la pulsacion larga abre el mismo menu",
                 rows == ["Copiar mensaje", "Seleccionar texto"]),
                ("el texto del usuario no se selecciona solo",
                 before == "none"),
            ]
            await js("document.querySelectorAll('.ctxrow')[1].click()")
            await asyncio.sleep(0.3)
            s2 = await js(SEL)
            print("  tactil    : %s" % s2)
            checks.append(("aqui tambien pone los cursores",
                           s2 and s2["txt"] == "ajusta"
                           and s2["sel"] == "text"))
            await js(OUTSIDE)
            await asyncio.sleep(0.25)
            closed = await js(ROWS)
            print("  tactil fuera: %s" % closed)
            checks.append(("en tactil el menu se cierra con un toque fuera",
                           closed is None))

            # el pulso siguiente arranca limpio: sin cursores del anterior
            await js(LONG)
            await asyncio.sleep(0.7)
            rows2 = await js(ROWS)
            s3 = await js(SEL)
            print("  pulso 2   : %s | %s" % (rows2, s3))
            checks.append(("el pulso siguiente abre el menu sin cursores previos",
                           rows2 == ["Copiar mensaje", "Seleccionar texto"]
                           and s3["txt"] == "" and s3["sel"] == "none"))

            # y al vaciar la seleccion (toque fuera) el texto vuelve a su sitio
            await js("document.querySelectorAll('.ctxrow')[1].click()")
            await asyncio.sleep(0.3)
            await js("getSelection().removeAllRanges()")
            await asyncio.sleep(0.3)
            s4 = await js(SEL)
            print("  vaciado   : %s" % s4)
            checks.append(("al vaciar la seleccion el texto deja de seleccionarse",
                           s4["sel"] == "none"))
    return checks


raise SystemExit(report(asyncio.run(main())))
