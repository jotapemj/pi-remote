"""El boton '+' del compositor: se queda visible al escribir, abre un popup
con Commands e Image (transicion, dismiss tocando fuera), y 'Commands' abre
la paleta sin robar el foco ni hacer amago. Teclear '/' tambien la abre.
"""
import asyncio

from harness import Bridge, Page, report


async def main():
    with Bridge():
        async with Page(port=9304) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")
            checks = []

            # el '+' es un icono y se queda visible aunque escribas
            vacio = await js("[!!$('#slashBtn').querySelector('svg'),"
                             " Number(getComputedStyle($('#slashBtn')).opacity)]")
            await js("box.value='hola'; box.dispatchEvent(new Event('input'))")
            await asyncio.sleep(0.1)
            typing = await js("Number(getComputedStyle($('#slashBtn')).opacity)")
            await js("box.value=''; box.dispatchEvent(new Event('input'))")
            print("  '+': icono=%s opac vacio=%s escribiendo=%s"
                  % (vacio[0], vacio[1], typing))
            checks += [
                ("el '+' es un icono", vacio[0] is True),
                ("visible con el campo vacio", vacio[1] == 1),
                ("y sigue visible al escribir (no se desvanece)", typing == 1),
            ]

            # abre el popup: dos items con titulo, animado
            await js("$('#slashBtn').click()")
            await asyncio.sleep(0.25)
            pop = await js("(() => {"
                " const m = $('#plusMenu');"
                " const it = [...m.querySelectorAll('.pmi')];"
                " return [m.classList.contains('open'),"
                "  Number(getComputedStyle(m).opacity),"
                "  it.map(b => b.dataset.act).join(','),"
                "  it.map(b => b.textContent.trim()).join('|'),"
                "  it.every(b => !!b.querySelector('svg'))];})()")
            print("  popup: open=%s opac=%s acts=%s titulos=%r iconos=%s"
                  % tuple(pop))
            checks += [
                ("el '+' abre el popup", pop[0] is True and pop[1] == 1),
                ("con Commands e Image", pop[2] == "commands,image"),
                ("cada item con su titulo", "|" in pop[3]
                 and all(pop[3].split("|"))),
                ("y su icono", pop[4] is True),
            ]

            # dismiss tocando fuera
            await js("document.dispatchEvent(new PointerEvent('pointerdown',"
                     "{bubbles:true}))")
            await asyncio.sleep(0.3)
            fuera = await js("$('#plusMenu').classList.contains('open')")
            checks.append(("se cierra tocando fuera", fuera is False))

            # 'Commands' abre la paleta, sin robar el foco (campo sin foco)
            await js("box.blur(); $('#slashBtn').click()")
            await asyncio.sleep(0.15)
            await js("[...document.querySelectorAll('#plusMenu .pmi')]"
                     ".find(b => b.dataset.act === 'commands').click()")
            await asyncio.sleep(0.2)
            cmd = await js("[box.value, $('#palette').classList.contains('open'),"
                           " document.querySelectorAll('.cmd').length,"
                           " document.activeElement.id]")
            print("  commands: valor=%r paleta=%s n=%s foco=%r"
                  % (cmd[0], cmd[1], cmd[2], cmd[3]))
            checks += [
                ("Commands escribe la barra y abre la paleta",
                 cmd[0] == "/" and cmd[1] is True and cmd[2] > 0),
                ("sin robar el foco ni abrir teclado", cmd[3] != "box"),
            ]
            await js("main.dispatchEvent(new Event('pointerdown'))")
            await asyncio.sleep(0.2)

            # el '+' con el campo enfocado suelta el foco: en el movil eso
            # evita que se reabra el teclado al pulsarlo
            await js("box.value=''; box.dispatchEvent(new Event('input'));"
                     " box.focus()")
            await asyncio.sleep(0.05)
            before = await js("document.activeElement === box")
            await js("$('#slashBtn').click()")
            await asyncio.sleep(0.15)
            kb = await js("[document.activeElement === box,"
                          " $('#plusMenu').classList.contains('open')]")
            print("  '+' con foco: antes=%s -> foco=%s popup=%s"
                  % (before, kb[0], kb[1]))
            checks += [
                ("el '+' suelta el foco del textarea (no reabre teclado)",
                 before is True and kb[0] is False),
                ("y aun asi abre el popup", kb[1] is True),
            ]

            # Commands abre la paleta y se queda abierta (sin amago)
            await js("const c=[...document.querySelectorAll('#plusMenu .pmi')]"
                     ".find(b=>b.dataset.act==='commands');"
                     " c.dispatchEvent(new MouseEvent('mousedown',"
                     "{bubbles:true,cancelable:true})); c.click()")
            amago0 = await js("$('#palette').classList.contains('open')")
            await asyncio.sleep(0.25)
            amago1 = await js("$('#palette').classList.contains('open')")
            print("  amago: abre=%s sigue=%s" % (amago0, amago1))
            checks.append(("la paleta se queda abierta (sin amago)",
                           amago0 is True and amago1 is True))
            await js("main.dispatchEvent(new Event('pointerdown'))")
            await asyncio.sleep(0.2)

            # el item Image esta cableado a un input de solo imagenes
            await js("box.value=''; box.dispatchEvent(new Event('input'))")
            img = await js("[$('#imgInput').accept, $('#imgInput').type,"
                           " !!$('#plusMenu .pmi[data-act=image]')]")
            print("  image: accept=%r type=%r item=%s" % tuple(img))
            checks += [
                ("el item Image existe", img[2] is True),
                ("y abre un selector de solo imagenes",
                 img[0] == "image/*" and img[1] == "file"),
            ]

            # teclear '/' tambien abre la paleta
            await js("box.value='/'; box.dispatchEvent(new Event('input'))")
            await asyncio.sleep(0.15)
            slash = await js("$('#palette').classList.contains('open')")
            checks.append(("teclear '/' abre la paleta", slash is True))

            checks.append(("sin errores de consola", not p.problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
