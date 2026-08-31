"""El texto que no cabe se desplaza; el que cabe, no. Sin prompts."""
import asyncio
import json

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

            # se mueve de verdad
            vistos = set()
            for _ in range(20):
                v = await js(SHIFT)
                if isinstance(v, (int, float)):     # el dom pudo repintarse
                    vistos.add(int(v))
                await asyncio.sleep(0.3)
            print("  desplazamientos vistos:", sorted(vistos))

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
            ]
            return report(checks)

raise SystemExit(asyncio.run(main()))
