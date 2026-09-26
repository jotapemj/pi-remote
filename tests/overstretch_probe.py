"""Fin de lista en el chat: estirado estilo Android 12+ al tirar mas alla
del borde (Chrome Android no lo pinta en contenedores internos). Gestos
tactiles reales por el protocolo de depuracion: arriba y abajo estira desde
ese borde, en mitad de la lista no, al soltar vuelve a 1, y con agente de
iPhone no actua (su rebote es nativo).
"""
import asyncio

from harness import Bridge, Page, report

FILL = """(() => {
  feed.innerHTML = '';
  for(let i = 0; i < 40; i++){
    const d = document.createElement('div');
    d.style.height = '60px'; d.textContent = 'linea ' + i;
    feed.appendChild(d);
  }
  main.style.scrollBehavior = 'auto';
  return main.scrollHeight > main.clientHeight;})()"""

SCALE = """(() => { const t = getComputedStyle(feed).transform;
  if(t === 'none') return 1;
  return +t.match(/matrix\\(([^)]+)\\)/)[1].split(',')[3]; })()"""


async def touch(p, kind, x, y):
    pts = [] if kind == "touchEnd" else [{"x": x, "y": y}]
    await p.cmd("Input.dispatchTouchEvent", type=kind, touchPoints=pts)


async def drag(p, x, y0, y1, steps=8):
    """Arrastre hasta y1 SIN soltar: devuelve la escala a mitad de gesto."""
    await touch(p, "touchStart", x, y0)
    for i in range(1, steps + 1):
        await touch(p, "touchMove", x, y0 + (y1 - y0) * i / steps)
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.05)
    return await p.js(SCALE)


async def setup(p, ua=None):
    await p.cmd("Emulation.setDeviceMetricsOverride", width=412, height=860,
                deviceScaleFactor=1, mobile=True)
    await p.cmd("Emulation.setTouchEmulationEnabled", enabled=True,
                maxTouchPoints=1)
    await p.cmd("Emulation.setEmitTouchEventsForMouse", enabled=True,
                configuration="mobile")
    if ua:
        await p.cmd("Emulation.setUserAgentOverride", userAgent=ua)
    await p.go()
    await asyncio.sleep(0.8)
    return await p.js(FILL)


async def main_():
    checks = []
    with Bridge():
        async with Page(port=9432) as p:
            scrolls = await setup(p)
            coarse = await p.js("COARSE.matches")
            r = await p.js("(()=>{const b=main.getBoundingClientRect();"
                           "return [b.left+b.width/2, b.top, b.bottom];})()")
            x, top, bot = r
            # arriba del todo, tirando hacia abajo
            await p.js("main.scrollTop = 0")
            s_top = await drag(p, x, top + 60, top + 360)
            origin_top = await p.js("feed.style.transformOrigin")
            await touch(p, "touchEnd", 0, 0)
            await asyncio.sleep(0.6)
            back = await p.js(SCALE)
            # al fondo, tirando hacia arriba
            await p.js("main.scrollTop = main.scrollHeight")
            await asyncio.sleep(0.1)
            s_bot = await drag(p, x, bot - 60, bot - 360)
            origin_bot = await p.js("feed.style.transformOrigin")
            await touch(p, "touchEnd", 0, 0)
            await asyncio.sleep(0.6)
            # a media lista: el gesto scrollea, no estira
            await p.js("main.scrollTop = 800")
            await asyncio.sleep(0.1)
            s_mid = await drag(p, x, top + 200, top + 260, steps=3)
            await touch(p, "touchEnd", 0, 0)
            print("  coarse=%s desborda=%s arriba=%.4f (%s) vuelta=%.4f "
                  "abajo=%.4f (%s) media=%.4f"
                  % (coarse, scrolls, s_top, origin_top, back, s_bot,
                     origin_bot, s_mid))
            checks += [
                ("tactil: el chat tiene desborde", coarse and scrolls),
                ("arriba del todo, tirar estira desde el borde de arriba",
                 1.01 < s_top <= 1.07 and origin_top.startswith("50% 0")),
                ("al soltar vuelve a su tamano", back == 1),
                ("al fondo, estira desde el borde de abajo",
                 1.01 < s_bot <= 1.07 and origin_bot.endswith("100%")),
                ("a media lista no estira", s_mid == 1),
            ]

        # iPhone: el rebote es nativo, el nuestro no actua
        async with Page(port=9433) as p:
            await setup(p, ua="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like "
                               "Mac OS X) AppleWebKit/605.1.15 (KHTML, like "
                               "Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
            r = await p.js("(()=>{const b=main.getBoundingClientRect();"
                           "return [b.left+b.width/2, b.top];})()")
            await p.js("main.scrollTop = 0")
            s_ios = await drag(p, r[0], r[1] + 60, r[1] + 360)
            await touch(p, "touchEnd", 0, 0)
            print("  iphone: escala=%.4f" % s_ios)
            checks.append(("en iPhone no actua (rebote nativo)", s_ios == 1))
    return checks


raise SystemExit(report(asyncio.run(main_())))
