"""El telon del arranque, el centrado del titulo y el fade del subtitulo."""
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
            # el telon: se va solo, y mientras esta tapa la cabecera
            telon = await js("(() => {"
                             " const b = $('#curtain');"
                             " if(!b) return null;"
                             " const fue = b.classList.contains('gone');"
                             " const r = b.getBoundingClientRect();"
                             " const cs = getComputedStyle(b);"
                             " const plate ="
                             " document.querySelector('.plate')"
                             ".getBoundingClientRect();"
                             " const out = [fue, Math.round(r.width),"
                             "  Math.round(r.height), Number(cs.opacity),"
                             "  Number(cs.zIndex), b.textContent.trim(),"
                             "  r.top <= plate.top && r.bottom >= plate.bottom];"
                             " return out; })()")
            print("\n  telon: se fue=%s %sx%s opacidad=%s z=%s %r tapa=%s"
                  % tuple(telon))
            # el telon retirado sigue midiendo la pantalla entera, pero
            # ya no se ve: eso es lo que hay que comprobar de los dos
            await js("$('#curtain').classList.remove('gone')")
            await asyncio.sleep(0.45)
            vuelto = await js("Number(getComputedStyle($('#curtain'))"
                              ".opacity)")
            await js("$('#curtain').classList.add('gone')")
            await asyncio.sleep(0.45)
            ido = await js("[Number(getComputedStyle($('#curtain'))"
                           ".opacity),"
                           " getComputedStyle($('#curtain')).visibility]")
            print("  telon: puesto opacidad=%s, quitado %s" % (vuelto, ido))
            cubre = (telon[0] is True and vuelto == 1 and ido[0] == 0
                     and ido[1] == "hidden" and telon[5] == "pi-remote"
                     and telon[6] is True and telon[4] == 60
                     and telon[1] >= 300 and telon[2] >= 600)

            # la "i" de la nota, al medio aunque el texto ocupe dos lineas
            await js("""
              feed.innerHTML = ""; nodes.clear();
              render({id:1, kind:"note", level:"info", key:"project",
                      args:{path:"C:\\\\Users\\\\user\\\\Desktop"
                                 + "\\\\Android Studio Projects"
                                 + "\\\\my-app"},
                      text:"project"});
            """)
            await asyncio.sleep(0.25)
            nota = await js("(() => {"
                            " const n = document.querySelector('.note');"
                            " const i = n.querySelector('svg');"
                            " const nr = n.getBoundingClientRect();"
                            " const ir = i.getBoundingClientRect();"
                            " return [Math.round(nr.height),"
                            "  Math.round(ir.top + ir.height/2 - nr.top),"
                            "  Math.round(nr.height/2)]; })()")
            print("  nota: alto=%s icono a %s (medio %s)" % tuple(nota))
            iconoOk = nota[0] > 30 and abs(nota[1] - nota[2]) <= 1

            print("  el telon cubre y se retira   : %s" % cubre)
            print("  la i de la nota, centrada    : %s" % iconoOk)
            print("\n" + ("TODO OK" if centrado and sube and estable
                          and cubre and iconoOk else "FALLA"))

raise SystemExit(asyncio.run(main()))
