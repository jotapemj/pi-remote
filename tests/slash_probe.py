"""El boton de barra: aparece con el campo vacio, se va al escribir."""
import asyncio
import json

from harness import Bridge, FakeProject, Page, ROOT, URL, report

MEASURE = """(() => {
  const b = getComputedStyle(document.querySelector('#slashBtn'));
  const t = getComputedStyle(document.querySelector('#box'));
  const m = new DOMMatrixReadOnly(b.transform);
  return [Number(b.opacity).toFixed(2), Math.round(m.a * 100) / 100,
          t.paddingLeft, b.pointerEvents];
})()"""

TYPE = ("box.value = %s;"
        " box.dispatchEvent(new Event('input'));")

async def main():
    with Bridge():
        async with Page(port=9304) as p:
            js, cmd = p.js, p.cmd
            await p.go()

            print("  fase              opacidad  escala  padding  clicable")

            async def row(label):
                v = await js(MEASURE)
                print("  %-17s %-9s %-7s %-8s %s"
                      % (label, v[0], v[1], v[2], v[3]))
                return v

            vacio = await row("campo vacio")
            await js(TYPE % "'hola'")
            await asyncio.sleep(0.07)
            medio = await row("escribiendo 70ms")
            await asyncio.sleep(0.5)
            lleno = await row("con texto")
            await js(TYPE % "''")
            await asyncio.sleep(0.5)
            vuelve = await row("borrado")

            # el boton escribe la barra y abre el panel
            await js("$('#slashBtn').click()")
            await asyncio.sleep(0.3)
            val = await js("[box.value, !$('#palette').classList.contains('open'),"
                           " document.querySelectorAll('.cmd').length,"
                           " document.activeElement.id]")
            await js("main.dispatchEvent(new Event('pointerdown'))")
            await asyncio.sleep(0.25)
            after = await js("[box.value, !$('#palette').classList.contains('open'), Number("
                             "getComputedStyle($('#slashBtn')).opacity)]")
            print("  foco tras pulsar: %r | tras tocar fuera: valor %r,"
                  " panel oculto %s, boton %s"
                  % (val[3], after[0], after[1], after[2]))
            print("\n  al pulsarlo: valor %r, panel oculto %s, %d comandos"
                  % (val[0], val[1], val[2]))

            # el amago: con el textarea enfocado, clicar '/' abria el panel y
            # se cerraba solo (el blur del textarea disparaba closePalette)
            await js("box.value=''; box.dispatchEvent(new Event('input'));"
                     " box.focus()")
            await asyncio.sleep(0.1)
            await js("$('#slashBtn').dispatchEvent(new MouseEvent('mousedown',"
                     "{bubbles:true, cancelable:true})); $('#slashBtn').click()")
            amago0 = await js("[$('#palette').classList.contains('open'),"
                              " document.activeElement === box]")
            await asyncio.sleep(0.25)                 # pasar los 150ms del blur
            amago1 = await js("$('#palette').classList.contains('open')")
            print("  amago: abre=%s foco_en_box=%s  sigue_abierta=%s"
                  % (amago0[0], amago0[1], amago1))
            await js("main.dispatchEvent(new Event('pointerdown'))")
            await asyncio.sleep(0.2)

            ok = [
                ("visible con el campo vacio", float(vacio[0]) == 1),
                ("hueco reservado", vacio[2] == "48px"),
                ("anima al salir", 0 < float(medio[0]) < 1),
                ("oculto con texto", float(lleno[0]) == 0),
                ("no clicable oculto", lleno[3] == "none"),
                ("el campo recupera su margen", lleno[2] == "20px"),
                ("vuelve al borrar", float(vuelve[0]) == 1),
                ("escribe la barra", val[0] == "/"),
                ("abre el panel", val[1] is False and val[2] > 0),
                ("no roba el foco ni abre teclado", val[3] != "box"),
                ("tocar fuera cierra y limpia la barra",
                 after[0] == "" and after[1] is True and after[2] == 1),
                ("con el campo enfocado el '/' no hace amago",
                 amago0[0] is True and amago1 is True),
                ("y no le quita el foco al textarea", amago0[1] is True),
            ]
            print()
            for name, good in ok:
                print("  " + ("ok    " if good else "FALLA ") + name)
            print("\n" + ("TODO OK" if all(g for _, g in ok) else "FALLA"))

raise SystemExit(asyncio.run(main()))
