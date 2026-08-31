"""Mide la animacion de apertura y de cierre. No habla con el agente."""
import asyncio
import json

from harness import Bridge, FakeProject, Page, ROOT, URL, report

# devuelve opacidad del velo y desplazamiento de la tarjeta
SAMPLE = """(() => {
  const o = getComputedStyle(document.querySelector('%s'));
  const c = getComputedStyle(document.querySelector('%s'));
  const m = new DOMMatrixReadOnly(c.transform);
  return [Number(o.opacity).toFixed(2), o.visibility,
          Math.round(m.m42), Math.round(m.a * 100) / 100];
})()"""

async def main():
    with Bridge():
        async with Page(port=9302) as p:
            js, cmd = p.js, p.cmd
            await p.go()

            async def trace(name, outer, inner, open_js, close_js):
                sample = SAMPLE % (outer, inner)
                print("\n" + name)
                print("  fase           opacidad  visible   despl  escala")

                async def row(label):
                    v = await js(sample)
                    print("  %-14s %-9s %-9s %-6s %s"
                          % (label, v[0], v[1], v[2], v[3]))
                    return v

                await row("cerrado")
                await js(open_js)
                await asyncio.sleep(0.09)
                mid_in = await row("abriendo 90ms")
                await asyncio.sleep(0.6)
                await row("abierto")
                await js(close_js)
                await asyncio.sleep(0.09)
                mid_out = await row("cerrando 90ms")
                await asyncio.sleep(0.6)
                end = await row("cerrado del todo")

                ok_in = 0 < float(mid_in[0]) < 1
                ok_out = 0 < float(mid_out[0]) < 1
                ok_end = end[1] == "hidden"
                print("  entrada anima: %s | salida anima: %s | se oculta: %s"
                      % (ok_in, ok_out, ok_end))
                return ok_in and ok_out and ok_end

            a = await trace("MODAL", "#modal", "#modal .mcard",
                            "aboutModal()", "closeModal()")
            b = await trace("BOTTOM SHEET", "#sheet", "#sheet .card",
                            "menuSheet()",
                            "$('#sheet').classList.remove('open')")
            c = await trace("PALETA DE COMANDOS", "#palette", "#palette",
                            "$('#slashBtn').click()",
                            "main.dispatchEvent(new Event('pointerdown'))")
            b = b and c
            print("\nTODO OK" if a and b else "\nFALLA")

raise SystemExit(asyncio.run(main()))
