"""Las tablas GFM se renderizan como <table>, no como texto con | y ---.

Se cubren: estructura (thead/tbody, columnas, filas), celdas vacias, que no
queda ningun residuo de pipes ni de la fila separadora, la alineacion por
:--- / :-: / ---: y el pipe escapado \\|. Sin tocar al agente de verdad.
"""
import asyncio
import json
import os

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


# una celda con prosa larga: antes nowrap estiraba la tabla a lo ancho
TABLE_LONG = "\n".join([
    "| Opcion | Descripcion |",
    "|---|---|",
    "| A | " + "texto largo que no deberia estirar la tabla " * 6 + "|",
    "| B | corto |",
])

# la tabla de la captura de JP: columna corta junto a prosa y enlaces largos.
# Con break-word salia "Ci/er/to" y "Ve/re/di/ct/o"
TABLE_REVIEW = "\n".join([
    "| Afirmación mía | Veredicto | Fuente |",
    "|---|---|---|",
    "| microSD = monolito (controlador + NAND en un paquete) | Cierto |"
    " [Rossmann - Monolithic NAND](https://example.com/a) |",
    "| Lijar el epoxi + bonding a pads del die es el método real | Cierto |"
    " [DrWizTech](https://example.com/b), Rossmann |",
    "| 16 GB SDHC -> FAT32 | Cierto | [SDA - Capacity](https://example.com/c),"
    " [Kingston SDC4 support](https://example.com/d) |",
])

# ninguna palabra partida: cada palabra de la celda mide lo mismo sola que
# dentro de la celda (un span por palabra, misma fila = misma top)
NOBREAK_STATE = """(() => {
  const cells = [...document.querySelectorAll('.said th, .said td')];
  let broken = [];
  for(const c of cells){
    for(const w of c.textContent.split(/\s+/).filter(Boolean)){
      const r = document.createRange();
      const walker = document.createTreeWalker(c, NodeFilter.SHOW_TEXT);
      let n, hit = false;
      while(!hit && (n = walker.nextNode())){
        const i = n.data.indexOf(w);
        if(i < 0) continue;
        r.setStart(n, i); r.setEnd(n, i + w.length);
        if(r.getClientRects().length > 1) broken.push(w);
        hit = true;
      }
    }
  }
  const t = document.querySelector('.said table');
  const w = document.querySelector('.said .twrap');
  return {broken, table: t.offsetWidth, wrap: w.clientWidth};
})()"""

LONG_STATE = """(() => {
  const w = document.querySelector('.said .twrap');
  const t = w.querySelector('table');
  const td = t.querySelector('tbody td:nth-child(2)');
  const lh = parseFloat(getComputedStyle(td).lineHeight);
  return {table: t.offsetWidth, wrap: w.clientWidth,
          scroll: w.scrollWidth, lines: Math.round(
            (td.clientHeight - 12) / lh)};
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

            # --- texto largo: parte en lineas, la tabla cabe en el ancho
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:3, kind:'assistant', streaming:false,"
                     " text:%s}); paint();" % json.dumps(TABLE_LONG))
            await asyncio.sleep(0.2)
            lg = await js(LONG_STATE)
            print("  larga:", json.dumps(lg))
            checks += [
                ("una celda larga no estira la tabla (sin scroll lateral)",
                 lg["scroll"] <= lg["wrap"] + 1
                 and lg["table"] <= lg["wrap"] + 1),
                ("la celda larga parte en varias lineas", lg["lines"] >= 2),
            ]

            # --- la tabla de la captura: sin palabras partidas
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:4, kind:'assistant', streaming:false,"
                     " text:%s}); paint();" % json.dumps(TABLE_REVIEW))
            await asyncio.sleep(0.2)
            if os.environ.get("PI_SHOT"):
                await p.shot(os.environ["PI_SHOT"])
            rv = await js(NOBREAK_STATE)
            print("  captura:", json.dumps(rv, ensure_ascii=True))
            checks += [
                ("ninguna palabra se parte por dentro",
                 rv["broken"] == []),
                ("y la tabla cabe en el ancho del chat",
                 rv["table"] <= rv["wrap"] + 1),
            ]

            checks.append(("sin errores de consola en el navegador",
                           not p.problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
