"""Comprueba el centrado del titulo y el fade del subtitulo."""
import asyncio
import json

from harness import Bridge, FakeProject, Page, ROOT, URL, report

MEASURE = """(() => {
  const p = document.querySelector('.plate');
  const h = document.querySelector('#title');
  const s = document.querySelector('#sub');
  const cs = getComputedStyle(s);
  const pr = p.getBoundingClientRect(), hr = h.getBoundingClientRect();
  return {plate: Math.round(pr.height),
          tituloCentro: Math.round(hr.top + hr.height/2 - pr.top),
          placaMedio: Math.round(pr.height/2),
          subOpacidad: Number(cs.opacity).toFixed(2),
          subAlto: cs.height,
          titulo: h.textContent};
})()"""

WITH_PROJECT = """
state = {running:false, waiting:false, alive:true,
  cwd:"C:\\\\proyectos\\\\demo",
  sessionName:"pantalla de ajustes", model:"Qwen3 14B", thinking:"medium",
  context:null, queue:{steering:[],followUp:[]}, recent:[]};
paint();
"""

async def main():
    with Bridge():
        async with Page(port=9303) as p:
            js, cmd = p.js, p.cmd
            await p.go()
            await js("setLang('es')")

            def show(label, m):
                print("  %-16s placa %3s  titulo a %3s (medio %3s)  "
                      "sub op %s alto %s"
                      % (label, m["plate"], m["tituloCentro"], m["placaMedio"],
                         m["subOpacidad"], m["subAlto"]))
                return m

            print("cabecera:")
            a = show("sin proyecto", await js(MEASURE))
            await js(WITH_PROJECT)
            await asyncio.sleep(0.12)
            show("a 120ms", await js(MEASURE))
            await asyncio.sleep(0.6)
            b = show("con proyecto", await js(MEASURE))

            centrado = abs(a["tituloCentro"] - a["placaMedio"]) <= 1
            sube = b["tituloCentro"] < a["tituloCentro"]
            estable = a["plate"] == b["plate"]
            print("\n  titulo centrado sin proyecto : %s" % centrado)
            print("  sube al cargar proyecto      : %s (%d -> %d)"
                  % (sube, a["tituloCentro"], b["tituloCentro"]))
            print("  la placa no cambia de alto   : %s (%d px)"
                  % (estable, a["plate"]))
            print("  subtitulo aparece            : %s -> %s"
                  % (a["subOpacidad"], b["subOpacidad"]))
            print("\n" + ("TODO OK" if centrado and sube and estable
                          else "FALLA"))

raise SystemExit(asyncio.run(main()))
