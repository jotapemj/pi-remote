"""Una respuesta, una familia: la fuente elegida en Apariencia manda en
todo el texto de la respuesta, titulos y negrita incluidos (el codigo va en
mono a proposito). Y la negrita usa un peso que la fuente trae de verdad:
con Serif pedia 700 a una @font-face declarada 400-600 y el navegador la
fabricaba (negrita sintetica), que se leia como otra letra.
"""
import asyncio
import sys

from harness import Bridge, Page, report

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MSG = "Texto con **negrita** y `code`.\\n\\n### Lo que esta bien\\n\\n- punto **uno**"

MEASURE = """(async () => {
  feed.innerHTML = ''; nodes.clear();
  render({id: 1, kind: 'assistant', streaming: false, text: "%s"});
  paint();
  await document.fonts.ready;
  const s = document.querySelector('.said');
  const fam = e => getComputedStyle(e).fontFamily;
  const p = s.querySelector('p'), h = s.querySelector('h4'),
        b = s.querySelector('strong'), c = s.querySelector('code');
  const w = getComputedStyle(b).fontWeight;
  const first = fam(p).split(',')[0].trim();
  return {p: fam(p), h: fam(h), b: fam(b), code: fam(c), weight: w,
          // la fuente trae ese peso de verdad (no hay que fabricarlo)
          real: document.fonts.check(w + ' 14px ' + first)};
})()""" % MSG


async def main():
    checks = []
    with Bridge():
        async with Page() as p:
            await p.go()
            await asyncio.sleep(0.8)
            for fid in ("sans", "inter", "serif", "mono"):
                await p.js("setFont('%s')" % fid)
                m = await p.js(MEASURE)
                print("  %s: %s" % (fid, m))
                checks += [
                    ("%s: titulo y negrita en la fuente elegida" % fid,
                     m["h"] == m["p"] and m["b"] == m["p"]),
                    ("%s: el codigo sigue en mono" % fid,
                     "Plex Mono" in m["code"]),
                    ("%s: negrita con un peso real de la fuente" % fid,
                     m["weight"] == "600" and m["real"]),
                ]
            problems = [x for x in p.problems if "favicon" not in x[1]]
            checks.append(("sin fallos en consola", not problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
