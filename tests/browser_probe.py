"""La pagina carga sin un solo error, y con todo montado."""
import asyncio

from harness import Bridge, Page, report

CHECKS = [
    ("el script llega al final", "typeof connect === 'function'", True),
    ("los iconos estan", "Object.keys(ICONS).length > 10", True),
    ("hamburguesa pintada", "!!document.querySelector('#railBtn svg')", True),
    ("ajustes pintado", "!!document.querySelector('#menuBtn svg')", True),
    ("enviar pintado", "!!document.querySelector('#send svg')", True),
    ("hueco vacio presente", "!!document.querySelector('#nostate')", True),
    ("la barra de lectura arranca oculta",
     "getComputedStyle(document.querySelector('#readout')).display", "none"),
    ("tema aplicado",
     "['dark','light'].includes(document.documentElement.dataset.theme)", True),
    ("la fuente propia esta en uso",
     "getComputedStyle(document.body).fontFamily.includes('Jakarta')", True),
    ("el socket abre", "ws ? ws.readyState : -1", 1),
    ("cabecera con el nombre del producto",
     "document.querySelector('#title').textContent.startsWith('pi-remote')",
     True),
]


async def main():
    with Bridge():
        async with Page(port=9301, collect_errors=True) as p:
            await p.go()
            await p.drain(2.0)

            print("  errores del navegador:", p.problems or "ninguno")
            checks = [("sin errores ni recursos que falten", not p.problems)]
            for label, expr, want in CHECKS:
                got = await p.js(expr)
                if got != want:
                    print("  %-34s %r (esperaba %r)" % (label, got, want))
                checks.append((label, got == want))
            return report(checks)


raise SystemExit(asyncio.run(main()))
