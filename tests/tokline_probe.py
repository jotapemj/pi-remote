"""Tokens del turno y tok/s en vivo.

- El puente suma el usage de TODAS las llamadas del turno (tambien las que
  solo lanzan una herramienta) en stats.turn: ↑ prompt, ↓ generado, R cache.
- Bajo la respuesta final se pinta la linea `↑ ↓ R`.
- Mientras genera, la barra de lectura da ~tok/s estimado por caracteres;
  callado (herramienta, pausa) desaparece.
Todo contra fake_pi (`cachehit`: 9000 sin cache, luego 500 + R9000).
"""
import asyncio
import json
import sys

from harness import Bridge, FakeProject, Page, report


sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # las flechas


async def until(p, expr, timeout=10.0, step=0.1):
    for _ in range(int(timeout / step)):
        if await p.js(expr):
            return True
        await asyncio.sleep(step)
    return False


async def main():
    checks = []
    with Bridge(), FakeProject() as proj:
        async with Page() as p:
            js = p.js
            await p.go()
            await asyncio.sleep(0.8)
            await js("setLang('es'); send({type:'open_project', path:%s})"
                     % json.dumps(proj.path))
            await until(p, "state.running === false")
            await asyncio.sleep(1.0)
            await js("send({type:'prompt', message:'cachehit'})")

            # durante el streaming: la barra da ~N tok/s
            seen = []
            for _ in range(20):
                t = await js("$('#rsecs').textContent + ' ' + $('#rtps').textContent")
                if t:
                    seen.append(t)
                if "tok/s" in (t or ""):
                    break
                await asyncio.sleep(0.15)
            live = [t for t in seen if "tok/s" in t]
            print("  barra:", seen[-4:])
            rate = None
            if live:
                try:
                    rate = int(live[-1].split("~")[1].split()[0])
                except (IndexError, ValueError):
                    pass
            checks += [
                ("en vivo la barra da ~tok/s", bool(live)),
                # 40 car cada 0.1 s = 100 tok/s; margen para el reloj del CI
                ("la estimacion cuadra (~100 tok/s)",
                 rate is not None and 50 <= rate <= 160),
            ]

            await until(p, "state.running === false")
            await asyncio.sleep(0.6)
            turn = await js("(() => { const t = [...nodes.values()]"
                            ".map(e => e.__item).filter(i => i && i.stats)"
                            ".pop(); return t ? t.stats.turn : null; })()")
            line = await js("""(() => { const e = document.querySelector(
              '.msgacts .tokline'); if(!e) return null;
              const r = e.getBoundingClientRect();
              return {text: e.textContent, w: r.width, h: r.height,
                      tip: e.dataset.tip}; })()""")
            after = await js("$('#rsecs').textContent + ' ' + $('#rtps').textContent")
            print("  turn:", turn, "| linea:", line, "| barra al parar:",
                  repr(after))
            checks += [
                ("el puente suma todas las llamadas del turno",
                 turn == {"input": 9500, "output": 180, "cacheRead": 9000}),
                ("la linea se pinta bajo la respuesta",
                 bool(line) and line["w"] > 0 and line["h"] > 0),
                ("con ↑ ↓ y R compactos",
                 bool(line) and line["text"] == "↑9.5k ↓180 R9k"),
                ("con su explicacion en el idioma activo",
                 bool(line) and (line["tip"] or "").startswith("Tokens del turno")),
                ("parado, la barra no da velocidad", "tok/s" not in after),
            ]

            # sin cache: no se pinta R; sin usage: no hay linea
            r2 = await js("[tokLine({input:12000, output:240, cacheRead:0}),"
                          " tokLine(null), tokLine({input:0, output:0})]")
            checks += [
                ("sin cache no sale R", "<b>R</b>" not in r2[0]),
                ("sin datos no hay linea", r2[1] == "" and r2[2] == ""),
            ]
            problems = [x for x in p.problems if "favicon" not in x[1]]
            checks.append(("sin fallos en consola", not problems))
            if problems:
                print(problems[:4])
    return checks


raise SystemExit(report(asyncio.run(main())))
