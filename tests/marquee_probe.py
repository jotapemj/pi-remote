"""El texto que no cabe se desplaza; el que cabe, no. Sin prompts."""
import asyncio
import json
import time

from harness import Bridge, FakeProject, Page, ROOT, URL, report

SEED = """
state = {running:false, waiting:false, alive:true, cwd:"",
  sessionName:null, model:null, thinking:null, context:null,
  queue:{steering:[],followUp:[]},
  recent:[
    {name:"ESP32S3_lab_devices_controller",
     path:"C:\\\\proyectos\\\\largo"},
    {name:"corto", path:"C:\\\\proyectos\\\\corto"}]};
window.__sent = []; ws.send = s => window.__sent.push(s);
paint(); openRail();
"""

ROW = """(() => {
  const b = document.querySelectorAll('.pgroup')[%d];
  const name = b.querySelector('.proj .txt > .mq');
  const cs = getComputedStyle(name);
  return [name.classList.contains('run'),
          name.style.getPropertyValue('--mq-shift'),
          name.style.getPropertyValue('--mq-dur'),
          cs.maskImage === 'none' ? 'sin mascara' : 'con degradado',
          getComputedStyle(name.firstElementChild).textOverflow,
          name.firstElementChild.scrollWidth, name.clientWidth];
})()"""

SHIFT = """(() => {
  const g = document.querySelectorAll('.pgroup')[0];
  const el = g && g.querySelector('.proj .txt > .mq > span');
  if(!el) return null;
  return Math.round(new DOMMatrixReadOnly(
    getComputedStyle(el).transform).m41);
})()"""

# estado de la marquesina: corriendo, pasadas, elipsis y si sabe que sobresale
RUN = """(() => {
  const g = document.querySelectorAll('.pgroup')[0];
  const el = g && g.querySelector('.proj .txt > .mq');
  if(!el) return null;
  const inner = el.firstElementChild;
  return [el.classList.contains('run'),
          getComputedStyle(inner).animationIterationCount,
          getComputedStyle(inner).textOverflow,
          el.__mqOver === true];
})()"""

BOX = """(() => {
  const g = document.querySelectorAll('.pgroup')[0];
  const el = g && g.querySelector('.proj .txt > .mq');
  if(!el) return null;
  const r = el.getBoundingClientRect();
  return [Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)];
})()"""


async def until_stopped(js, seconds=30):
    """espera a que la pasada termine (la duracion depende del texto)"""
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        st = await js(RUN)
        if st and st[0] is False:
            return st
        await asyncio.sleep(0.3)
    return None

async def main():
    with Bridge():
        async with Page(port=9307) as p:
            js, cmd = p.js, p.cmd
            await p.go()
            await js("setLang('es')")
            await js(SEED)
            await asyncio.sleep(1.0)

            plegado = await js(ROW % 0)
            await js('toggleProj("C:\\\\proyectos\\\\largo")')
            await asyncio.sleep(0.7)
            largo = await js(ROW % 0)
            corto = await js(ROW % 1)
            print("  nombre largo : run=%s shift=%s dur=%s %s"
                  % (largo[0], largo[1], largo[2], largo[3]))
            print("  nombre corto : run=%s %s  elipsis=%r"
                  % (corto[0], corto[3], corto[4]))
            print("  anchos largo : texto %s  hueco %s" % (largo[5], largo[6]))
            print("  anchos corto : texto %s  hueco %s" % (corto[5], corto[6]))

            # una pasada y parada: el bucle infinito marea
            corriendo = await js(RUN)

            # se mueve de verdad
            vistos = set()
            for _ in range(20):
                v = await js(SHIFT)
                if isinstance(v, (int, float)):     # el dom pudo repintarse
                    vistos.add(int(v))
                await asyncio.sleep(0.3)
            print("  desplazamientos vistos:", sorted(vistos))

            # se para solo, sin que nadie lo pare
            parada = await until_stopped(js)
            print("  parada    : %s" % parada)

            # y el raton encima la vuelve a arrancar (otra pasada, y para)
            box = await js(BOX)
            await p.cmd("Input.dispatchMouseEvent", type="mouseMoved",
                        x=box[0], y=box[1])
            await asyncio.sleep(0.35)
            hover = await js(RUN)
            print("  hover     : %s en %s" % (hover, box))
            de_nuevo = await until_stopped(js)
            print("  y para    : %s" % de_nuevo)

            checks = [
                ("quieto mientras esta plegado", plegado[0] is False),
                ("se desplaza al desplegarlo", largo[0] is True),
                ("el otro sigue quieto", corto[0] is False),
                ("con recorrido negativo",
                 largo[1].startswith("-") and largo[1].endswith("px")),
                ("y duracion propia", largo[2].endswith("s")),
                ("degradado solo mientras corre",
                 largo[3] == "con degradado" and corto[3] == "sin mascara"),
                ("el corto se queda quieto", corto[0] is False),
                ("y conserva elipsis", corto[4] == "ellipsis"),
                ("se mueve de verdad", len(vistos) >= 3),
                ("hubo muestras", len(vistos) > 0),
                ("y vuelve al origen", 0 in vistos),
                ("no se pasa del recorrido",
                 min(vistos) >= int(largo[1].replace("px", "")) - 2),
                ("una sola pasada", corriendo[1] == "1"),
                ("y se para solo", parada is not None),
                ("al parar recupera la elipsis",
                 parada is not None and parada[2] == "ellipsis"),
                ("el raton encima la reanuda", hover[0] is True),
                ("y vuelve a pararse sola", de_nuevo is not None),
            ]
            return report(checks)

raise SystemExit(asyncio.run(main()))
