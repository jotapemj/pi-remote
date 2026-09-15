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

            # dismiss tocando fuera: se cierra y el '+' pierde el borde acento.
            # El borde va por la clase .on (no por :focus), asi que en tactil,
            # donde el foco puede quedarse, el borde igual desaparece
            await js("if(!$('#plusMenu').classList.contains('open'))"
                     " $('#slashBtn').click()")
            on_abierto = await js("$('#slashBtn').classList.contains('on')")
            await js("document.dispatchEvent(new PointerEvent('pointerdown',"
                     "{bubbles:true}))")
            await asyncio.sleep(0.3)
            fuera = await js("[$('#plusMenu').classList.contains('open'),"
                             " $('#slashBtn').classList.contains('on')]")
            print("  dismiss: on antes=%s -> abierto=%s on=%s"
                  % (on_abierto, fuera[0], fuera[1]))
            checks += [
                ("se cierra tocando fuera", fuera[0] is False),
                ("y el '+' pierde el borde acento al cerrar (clase .on fuera)",
                 on_abierto is True and fuera[1] is False),
            ]

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

            # el boton de enviar: un '/' lo convierte en un check ambar, sea o no
            # que el agente este trabajando; enviarlo no debe bloquearse
            await js("try{if(ws)ws.onmessage=null;}catch(e){}")
            await js("state={running:false,waiting:false,alive:true,cwd:'C:/x',"
                     "sessionName:'s',model:'m',thinking:'x',context:null,"
                     "queue:{steering:[],followUp:[]},recent:[]}; CWD='C:/x'; paint()")
            await js("box.value='/name foo'; box.dispatchEvent(new Event('input'))")
            await asyncio.sleep(0.1)
            conf = await js("[$('#send').classList.contains('confirm'),"
                            " Number(getComputedStyle($('#send .chk')).opacity),"
                            " Number(getComputedStyle($('#send .halt')).opacity)]")
            print("  send con '/': confirm=%s ok=%s halt=%s" % tuple(conf))
            checks.append(("un '/' pone el boton de enviar en modo check",
                           conf[0] is True and conf[1] == 1 and conf[2] == 0))

            # el boton sigue redondo como la flecha: el icono no debe heredar el
            # fondo/padding del boton global .ok (colision de clase -> cuadrado)
            shape = await js("[getComputedStyle($('#send')).borderRadius,"
                             " getComputedStyle($('#send .chk')).backgroundColor,"
                             " getComputedStyle($('#send .chk')).padding]")
            print("  forma check: br=%s bg=%s pad=%s" % tuple(shape))
            checks.append(("el boton de check es redondo, sin fondo/padding heredado",
                           shape[0] == "50%"
                           and "rgba(0, 0, 0, 0)" in shape[1]
                           and shape[2] in ("0px", "")))

            # con el agente ocupado el check gana al cuadrado de parar
            await js("state.running=true; paint()")
            await asyncio.sleep(0.05)
            busyc = await js("[$('#send').classList.contains('confirm'),"
                             " Number(getComputedStyle($('#send .chk')).opacity)]")
            print("  send '/' con agente ocupado: confirm=%s ok=%s" % tuple(busyc))
            checks.append(("con el agente ocupado el '/' sigue mandando",
                           busyc[0] is True and busyc[1] == 1))

            # al pulsar, envia el comando (runLine) y no aborta el turno
            await js("window.__lines=[]; window.__sent=[]; window.__rl=runLine;"
                     " runLine=t=>{window.__lines.push(t); box.value='';};"
                     " ws.send=s=>window.__sent.push(JSON.parse(s));"
                     " $('#send').click()")
            await asyncio.sleep(0.05)
            click = await js("[window.__lines[0]||null,"
                             " !!window.__sent.find(x=>x.type==='abort')]")
            print("  click con '/': linea=%r abort=%s" % tuple(click))
            checks.append(("pulsar el check envia el comando y no aborta",
                           click[0] == "/name foo" and click[1] is False))

            # quitar el '/' revierte a enviar/parar
            await js("runLine=window.__rl; state.running=false; box.value='';"
                     " box.dispatchEvent(new Event('input')); paint()")
            await asyncio.sleep(0.05)
            gone = await js("$('#send').classList.contains('confirm')")
            checks.append(("quitar el '/' revierte el boton", gone is False))



            checks.append(("sin errores de consola", not p.problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
