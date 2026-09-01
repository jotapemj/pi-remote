"""Gestos tactiles: arrastrar para cerrar las hojas, deslizar para cerrar
la barra, y sin pull-to-refresh. Se disparan eventos de puntero sinteticos
en un viewport de movil. Sin agente real.
"""
import asyncio

from harness import Bridge, Page, report

# arrastra un elemento con puntero: baja (dx=0) o lateral, en pasos
DRAG = """(sel, x0, y0, dx, dy) => {
  const el = document.querySelector(sel);
  const ev = (type, x, y) => el.dispatchEvent(new PointerEvent(type, {
    clientX:x, clientY:y, pointerId:1, pointerType:'touch',
    bubbles:true, cancelable:true}));
  ev('pointerdown', x0, y0);
  const steps = 8;
  for(let i=1;i<=steps;i++) ev('pointermove', x0+dx*i/steps, y0+dy*i/steps);
  ev('pointerup', x0+dx, y0+dy);
  return true;
}"""


async def main():
    checks = []
    with Bridge():
        async with Page(port=9319, width=412, height=880, mobile=True) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")
            await js("window.__drag = " + DRAG)

            # pull-to-refresh apagado
            osb = await js("getComputedStyle(document.body).overscrollBehaviorY")
            print("  overscroll-behavior-y:", osb)
            checks.append(("sin pull-to-refresh del navegador", osb == "none"))

            # el agarre visible en movil
            await js("menuSheet()")
            await asyncio.sleep(0.4)
            grab = await js("(() => { const g ="
                            " document.querySelector('#sheet .grab');"
                            " return g && getComputedStyle(g).display !=="
                            " 'none'; })()")
            print("  agarre visible:", grab)
            checks.append(("la hoja muestra su agarre", grab is True))

            # touch-action deja el scroll al navegador
            ta = await js("[getComputedStyle($('#sheet .card')).touchAction,"
                          " getComputedStyle($('#rail')).touchAction,"
                          " getComputedStyle($('#sheet .grab')).touchAction]")
            print("  touch-action card/rail/grab:", ta)
            checks.append(("el scroll se lo queda el navegador (pan-y)",
                           ta[0] == "pan-y" and ta[1] == "pan-y"
                           and ta[2] == "none"))

            # arrastrar el CUERPO (no la barrita) no cierra: eso es scroll
            await js("__drag('#sheet .card', 200, 300, 0, 220)")
            await asyncio.sleep(0.4)
            body = await js("$('#sheet').classList.contains('open')")
            print("  tras arrastrar el cuerpo 220px, abierta:", body)
            checks.append(("arrastrar el cuerpo no cierra: es scroll",
                           body is True))

            # arrastrar poco -> vuelve (sigue abierta)
            await js("__drag('#sheet .grab', 200, 200, 0, 30)")
            await asyncio.sleep(0.4)
            still = await js("$('#sheet').classList.contains('open')")
            print("  tras arrastrar 30px, abierta:", still)
            checks.append(("un tiron corto rebota y no cierra", still is True))

            # arrastrar fuerte -> cierra
            await js("__drag('#sheet .grab', 200, 200, 0, 220)")
            await asyncio.sleep(0.5)
            closed = await js("$('#sheet').classList.contains('open')")
            print("  tras arrastrar 220px, abierta:", closed)
            checks.append(("un arrastre largo cierra la hoja",
                           closed is False))

            # la hoja de estadisticas, igual
            await js("statsSheet({output:10,input:100,total:110,cacheRead:0,"
                     "reasoning:0,cost:0,genTps:5,promptTps:100})")
            await asyncio.sleep(0.35)
            await js("__drag('#statsheet .grab', 200, 300, 0, 220)")
            await asyncio.sleep(0.5)
            stClosed = await js("$('#statsheet').classList.contains('open')")
            checks.append(("la hoja de estadisticas tambien se arrastra",
                           stClosed is False))

            # la barra: deslizar a la izquierda la cierra
            await js("openRail()")
            await asyncio.sleep(0.4)
            openedRail = await js("$('#rail').classList.contains('on')")
            await js("__drag('#rail', 150, 300, -160, 0)")
            await asyncio.sleep(0.5)
            railClosed = await js("$('#rail').classList.contains('on')")
            print("  barra: abierta=%s -> tras deslizar=%s"
                  % (openedRail, railClosed))
            checks += [
                ("la barra se abre para la prueba", openedRail is True),
                ("deslizar a la izquierda la cierra", railClosed is False),
            ]

            # deslizar poco no la cierra
            await js("openRail()")
            await asyncio.sleep(0.4)
            await js("__drag('#rail', 150, 300, -30, 0)")
            await asyncio.sleep(0.4)
            stays = await js("$('#rail').classList.contains('on')")
            print("  barra tras deslizar 30px:", stays)
            checks.append(("un deslizamiento corto no cierra la barra",
                           stays is True))
    return checks


raise SystemExit(report(asyncio.run(main())))
