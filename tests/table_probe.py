"""Las tablas GFM se renderizan como <table>, no como texto con | y ---.

Se cubren: estructura (thead/tbody, columnas, filas), celdas vacias, que no
queda ningun residuo de pipes ni de la fila separadora, la alineacion por
:--- / :-: / ---: y el pipe escapado \\|. Sin tocar al agente de verdad.
"""
import asyncio
import json

from harness import Bridge, FakeProject, Page, report


# la tabla que trajo JP: primera celda de cabecera vacia, seis filas
TABLE_JP = "\n".join([
    "| | KB |",
    "|---|---|",
    "| Tool schemas | ~15 |",
    "| Skills | ~3 |",
    "| AGENTS.md global | ~1.6 |",
    "| CLAUDE.md proyecto | 12.1 |",
    "| system-reminder | ~0.4 |",
    "| Total | ~32 KB ≈ 9k tokens |",
])

# alineaciones y un pipe escapado dentro de una celda
TABLE_ALIGN = "\n".join([
    "| izq | cen | der |",
    "|:---|:--:|---:|",
    "| a | b | c |",
    "| x \\| y | m | n |",
])

JP_STATE = """(() => {
  const said = document.querySelector('.said');
  const t = said.querySelector('table');
  if(!t) return {table:false, text:said.textContent};
  const ths = [...t.querySelectorAll('thead th')];
  const rows = [...t.querySelectorAll('tbody tr')];
  const last = [...rows[rows.length-1].querySelectorAll('td')]
                 .map(td => td.textContent);
  const th0 = getComputedStyle(ths[0]);
  return {
    table:true,
    cols: ths.length,
    head0: ths[0].textContent,
    head1: ths[1].textContent,
    rows: rows.length,
    lastA: last[0], lastB: last[1],
    // residuos del renderer viejo: pipe suelto o la linea de guiones
    pipe: said.textContent.includes('|'),
    dashes: said.textContent.includes('---'),
    headColor: th0.color,
    headBorder: th0.borderBottomWidth,
    twrap: !!said.querySelector('.twrap'),
  };
})()"""

ALIGN_STATE = """(() => {
  const t = document.querySelector('.said table');
  const al = [...t.querySelectorAll('thead th')]
               .map(th => getComputedStyle(th).textAlign);
  const esc = [...t.querySelectorAll('tbody tr')][1]
                .querySelector('td').textContent;
  return {aligns: al, escaped: esc};
})()"""


async def main():
    checks = []
    with Bridge(), FakeProject():
        async with Page(port=9317) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")

            # --- la tabla de JP
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:1, kind:'assistant', streaming:false,"
                     " text:%s}); paint();" % json.dumps(TABLE_JP))
            await asyncio.sleep(0.25)
            s = await js(JP_STATE)
            print("  JP:", json.dumps(s, ensure_ascii=True))
            checks += [
                ("se genera una <table>, no texto crudo",
                 isinstance(s, dict) and s.get("table") is True),
                ("dos columnas, la primera cabecera vacia",
                 s.get("cols") == 2 and s.get("head0") == ""
                 and s.get("head1") == "KB"),
                ("seis filas de datos", s.get("rows") == 6),
                ("la ultima fila es Total / ~32 KB...",
                 s.get("lastA") == "Total"
                 and "9k tokens" in (s.get("lastB") or "")),
                ("no queda ningun pipe suelto de texto",
                 s.get("pipe") is False),
                ("no queda la fila de guiones", s.get("dashes") is False),
                ("va en un contenedor con scroll propio",
                 s.get("twrap") is True),
                ("la cabecera lleva su borde inferior grueso",
                 s.get("headBorder") == "2px"),
            ]

            # --- alineaciones y escape
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:2, kind:'assistant', streaming:false,"
                     " text:%s}); paint();" % json.dumps(TABLE_ALIGN))
            await asyncio.sleep(0.2)
            a = await js(ALIGN_STATE)
            print("  alineacion:", json.dumps(a, ensure_ascii=True))
            checks += [
                ("izquierda / centro / derecha se respetan",
                 a.get("aligns") == ["left", "center", "right"]),
                ("el pipe escapado queda literal en la celda",
                 a.get("escaped") == "x | y"),
            ]

            checks.append(("sin errores de consola en el navegador",
                           not p.problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
