"""Al abrirse el teclado, el maquetador sube y main se encoge. anchorKb
ancla el contenido al borde inferior: lo que asomaba encima del
maquetador se sigue viendo, sin tener que scrollear a compensar. Al
cerrar el teclado, la posicion previa vuelve."""
import asyncio

from harness import Bridge, Page, report

FILL = """(() => {
  const f = $('#feed');
  for(let i = 0; i < 40; i++){
    const d = document.createElement('div');
    d.style.height = '60px'; d.textContent = 'fila ' + i;
    f.appendChild(d);
  }
})()"""

UNDER = "main.scrollHeight - main.scrollTop - main.clientHeight"


async def main():
    checks = []
    with Bridge():
        async with Page(port=9421) as p:
            js = p.js
            await p.go()
            await js(FILL)

            # leyendo en mitad: lo que faltaba al borde inferior no cambia
            await js("jumpTo(300)")
            before = await js(UNDER)
            await js("anchorKb(300)")
            after = await js("[%s, getComputedStyle(document.documentElement)"
                             ".getPropertyValue('--kb')]" % UNDER)
            print("  mitad: under antes=%.1f despues=%.1f kb=%r"
                  % (before, after[0], after[1]))
            checks += [
                ("al abrir el teclado lo que faltaba al fondo no cambia",
                 abs(after[0] - before) < 2),
                ("la variable --kb se pone a 300px",
                 after[1].strip() == "300px"),
            ]

            # cerrar el teclado devuelve la posicion previa
            await js("anchorKb(0)")
            back = await js(UNDER)
            print("  cerrar: under=%.1f (antes %.1f)" % (back, before))
            checks.append(("al cerrar el teclado vuelve la posicion previa",
                           abs(back - before) < 2))

            # pegado al fondo: sigue pegado
            await js("jumpTo(main.scrollHeight)")
            await js("anchorKb(400)")
            atb = await js(UNDER)
            print("  fondo: under=%.1f" % atb)
            checks.append(("si estabas en el fondo, sigues en el fondo",
                           atb < 2))

            checks.append(("sin errores de consola", not p.problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
