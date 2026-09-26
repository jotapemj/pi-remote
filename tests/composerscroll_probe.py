"""Compositor con mas texto del que cabe: el scroll sigue al cursor en cada
salto de linea (al tope de alto, el cursor se quedaba por debajo del borde y
habia que bajar a mano), y el indicador de scroll no se mete bajo el boton de
enviar aunque las lineas lleguen hasta el. Teclas reales por el protocolo.
"""
import asyncio

from harness import Bridge, Page, report


async def key_enter(p):
    for kind in ("keyDown", "keyUp"):
        await p.cmd("Input.dispatchKeyEvent", type=kind, key="Enter",
                    code="Enter", windowsVirtualKeyCode=13, modifiers=8)


CARET = """(() => {
  const s = getSelection(); const r = s.getRangeAt(0).cloneRange();
  r.collapse(false);
  const b = box.getBoundingClientRect();
  const atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 2;
  return {over: box.scrollHeight - box.clientHeight, atEnd,
          top: box.scrollTop};})()"""


async def main():
    checks = []
    with Bridge():
        async with Page(port=9442) as p:
            js = p.js
            await p.cmd("Emulation.setDeviceMetricsOverride", width=1000,
                        height=700, deviceScaleFactor=1, mobile=False)
            await p.go()
            await asyncio.sleep(0.6)
            # sin proyecto la caja esta bloqueada: se desbloquea para medir
            await js("box.setAttribute('contenteditable','true');"
                     " box.textContent=''; box.focus()")
            # lineas hasta pasar el alto maximo (38vh), cada una con Enter
            for i in range(24):
                await p.cmd("Input.insertText", text="linea %d" % i)
                await key_enter(p)
                await asyncio.sleep(0.03)
            await asyncio.sleep(0.2)
            c = await js(CARET)
            # a media escritura: subir y escribir abajo otra vez
            await js("box.scrollTop = 0")
            await p.cmd("Input.insertText", text="mas")
            await key_enter(p)
            await asyncio.sleep(0.2)
            c2 = await js(CARET)
            print("  tras 24 lineas: %s  tras subir y seguir: %s" % (c, c2))
            checks += [
                ("la caja llega a su tope y desborda", c["over"] > 50),
                ("el cursor sigue a la vista tras cada Enter", c["atEnd"]),
                ("aunque se hubiera subido antes, al escribir vuelve",
                 c2["atEnd"]),
            ]

            # indicador: lineas anchas hasta el hueco del boton de enviar
            await js("""box.textContent = Array.from({length:30}, () =>
              'palabras largas que llenan la linea hasta el borde del campo '
              + 'y siguen').join(' ');
              box.dispatchEvent(new Event('input'));
              $('#field').classList.add('typing');""")
            await asyncio.sleep(0.4)
            ind = await js("""(() => {
              paintScrollInd();
              const i = $('#scrollInd').getBoundingClientRect(),
                    s = $('#send').getBoundingClientRect();
              return {right: i.right, send: s.left,
                      vis: getComputedStyle($('#scrollInd')).opacity,
                      sendVis: getComputedStyle($('#send')).opacity};})()""")
            print("  indicador: %s" % ind)
            checks.append(("el indicador de scroll queda a la izquierda "
                           "del boton de enviar",
                           ind["vis"] == "1" and ind["right"] <= ind["send"] - 4))

            # escritorio: ejecutar un comando no quita el foco (no hay
            # teclado que tape y el foco es comodo)
            desk = await js("""(() => { box.textContent = ''; box.focus();
              choose(CMDS.find(c => c.n === 'stats'));
              const f = document.activeElement === box; closeModal();
              return f; })()""")
            checks.append(("escritorio: el comando no quita el foco", desk))

        # tactil: un comando que abre dialogo u hoja esconde el teclado
        async with Page(port=9443) as p:
            js = p.js
            await p.cmd("Emulation.setDeviceMetricsOverride", width=412,
                        height=860, deviceScaleFactor=1, mobile=True)
            await p.cmd("Emulation.setTouchEmulationEnabled", enabled=True,
                        maxTouchPoints=1)
            await p.go()
            await asyncio.sleep(0.6)
            k = await js("""(() => {
              const on = () => document.activeElement === box;
              const r = {coarse: COARSE.matches};
              box.setAttribute('contenteditable', 'true');
              // desde la paleta: /think abre una hoja
              box.focus(); box.value = '/'; paintPalette();
              choose(CMDS.find(c => c.n === 'think'));
              r.think = !on();
              $('#sheet').classList.remove('open');
              // escrito entero y enviado: /stats abre un dialogo
              box.focus(); box.value = '/stats'; runLine('/stats');
              r.stats = !on(); closeModal();
              // con argumento hay que seguir escribiendo: foco se queda
              box.focus(); choose(CMDS.find(c => c.n === 'name'));
              r.name = on();
              box.value = '';
              return r; })()""")
            print("  tactil: %s" % k)
            checks += [
                ("tactil: /think desde la paleta esconde el teclado",
                 k["coarse"] and k["think"]),
                ("tactil: /stats escrito y enviado tambien", k["stats"]),
                ("un comando con argumento conserva el foco para escribirlo",
                 k["name"]),
            ]
    return checks


raise SystemExit(report(asyncio.run(main())))
