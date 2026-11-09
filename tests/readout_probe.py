"""La barra de lectura no se pisa a si misma en un movil estrecho.

Palabra rotatoria + segundos + ~tok/s a la izquierda, barra de contexto a
la derecha. Con la palabra mas larga (aleman), un contador de tres cifras y
la velocidad, nada de la izquierda puede invadir la barra: la palabra se
recorta y los numeros se ven enteros. Se mide el pixel, no el nodo.
"""
import asyncio
import os
import sys

from harness import Bridge, Page, report

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SETUP = """(() => {
  setLang(%(lang)s);
  state.running = true; state.waiting = false;
  state.startedAt = Date.now() / 1000 - 123;
  state.context = {percent: 45.2, tokens: 59000, window: 131072};
  curWord = %(word)s;
  const now = Date.now();
  rateWin = [[now - 1000, 400], [now - 500, 250], [now - 50, 250]];
  produced = true; lastDelta = 0;
  const r = $('#readout'); r.hidden = false; r.classList.add('thinking');
  paintCtx(); paintStatus();
  $('#rword').textContent = wordText();
})()"""

MEASURE = """(() => {
  const R = e => e.getBoundingClientRect();
  const st = $('.rstat'), w = $('#rword'), s = $('#rsecs'), c = $('#bar');
  const t = $('#rtps');
  return {stat: R(st).right, word: R(w).right, secs: R(t).right,
          secsL: R(s).left, ctx: R(c).left, ctxW: R(c).width,
          wordClip: w.scrollWidth > w.clientWidth + 1,
          numsClip: s.scrollWidth > s.clientWidth + 1
                    || t.scrollWidth > t.clientWidth + 1,
          secsText: s.textContent + ' ' + t.textContent,
          wordText: w.textContent,
          label: c.querySelector('span').textContent,
          labelFits: c.querySelector('span').scrollWidth
                     <= c.querySelector('span').clientWidth + 1};
})()"""


async def main():
    checks = []
    with Bridge():
        for width in (412, 360, 320):
            async with Page(width=width) as p:
                await p.go()
                await asyncio.sleep(0.8)
                for lang, word in (("de", "Auskristallisierend"),
                                   ("es", "Tro-pi-calizando"),
                                   ("en", "Think")):
                    await p.js(SETUP % {"lang": repr(lang),
                                        "word": repr(word)})
                    await asyncio.sleep(0.5)       # la palabra entra con fundido
                    m = await p.js(MEASURE)
                    print("  %dpx %s: %s" % (width, lang, m))
                    tag = "%d px, %s" % (width, lang)
                    checks += [
                        ("%s: nada de la izquierda pisa la barra" % tag,
                         m["stat"] <= m["ctx"] + 0.5
                         and m["secs"] <= m["ctx"] + 0.5
                         and m["word"] <= m["ctx"] + 0.5),
                        ("%s: segundos y tok/s enteros y a la vista" % tag,
                         "tok/s" in m["secsText"] and not m["numsClip"]
                         and m["secsL"] >= 0 and m["secs"] <= m["ctx"]),
                    ]
                    if width >= 360:
                        # con sitio, la barra cede antes que la palabra
                        checks.append(("%s: la palabra corta no se recorta"
                                       % tag, lang != "en"
                                       or not m["wordClip"]))
                    checks += [
                        ("%s: la barra conserva su lectura" % tag,
                         m["labelFits"] and m["ctxW"] >= 120),
                    ]
                    if os.environ.get("PI_SHOT") and width == 360 \
                            and lang == "de":
                        await p.shot(os.environ["PI_SHOT"])
                problems = [x for x in p.problems if "favicon" not in x[1]]
                checks.append(("%d px: sin fallos en consola" % width,
                               not problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
