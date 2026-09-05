"""Fase 2: el compositor es un contenteditable. Pegar un bloque grande de
texto lo mete como chip "Texto pegado N lineas" en el punto del cursor,
respetando lo escrito antes y despues; el envio expande el chip a su texto
completo, en su sitio. Un pegado corto va llano. Una imagen pegada cae en la
fila de miniaturas. El placeholder solo asoma con el campo vacio.
"""
import asyncio
import json

from harness import Bridge, Page, report

BIG = "\n".join("line %d of pasted code" % i for i in range(1, 9))   # 8 lineas
SMALL = "just two\nlines"                                            # corto

PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP8"
       "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

# pega texto por un evento de verdad (clipboardData adjuntado a mano)
PASTE_TEXT = """(txt => {
  const dt = new DataTransfer(); dt.setData('text/plain', txt);
  const ev = new ClipboardEvent('paste', {bubbles:true, cancelable:true});
  Object.defineProperty(ev, 'clipboardData', {value: dt});
  box.focus(); box.dispatchEvent(ev);
})"""

PASTE_IMG = """(() => {
  const b = Uint8Array.from(atob('%s'), c => c.charCodeAt(0));
  const f = new File([b], 'x.png', {type:'image/png'});
  const dt = new DataTransfer(); dt.items.add(f);
  const ev = new ClipboardEvent('paste', {bubbles:true, cancelable:true});
  Object.defineProperty(ev, 'clipboardData', {value: dt});
  box.focus(); box.dispatchEvent(ev);
})()""" % PNG

TYPE = "(t => document.execCommand('insertText', false, t))"


async def main():
    checks = []
    with Bridge():
        async with Page(port=9361) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")
            await js("state={running:false,waiting:false,alive:true,cwd:'C:/x',"
                     "sessionName:'s',model:'m',thinking:'x',context:null,"
                     "queue:{steering:[],followUp:[]},recent:[]}; paint()")

            # placeholder solo con el campo vacio
            ph = await js("[box.classList.contains('ce-blank'),"
                          " !!box.dataset.ph, box.getAttribute('contenteditable')]")
            print("  vacio: empty=%s tiene_ph=%s editable=%r" % tuple(ph))
            checks += [
                ("el compositor arranca vacio y editable",
                 ph[0] is True and ph[2] == "true"),
                ("con marcador de posicion", ph[1] is True),
            ]

            # la barra bien encajada: la caja llena el campo y no colapsa, el
            # '+' queda dentro. (regresion: 'empty' choca con la tarjeta de
            # estado sin proyecto, que es absolute/centrada/300px)
            lay = await js("(() => {"
                           " const f = $('#field').getBoundingClientRect();"
                           " const b = $('#box').getBoundingClientRect();"
                           " const s = $('#slashBtn').getBoundingClientRect();"
                           " return [Math.round(f.height), Math.round(f.width),"
                           "  Math.round(b.width),"
                           "  getComputedStyle($('#box')).position,"
                           "  Math.round(s.left - b.left),"
                           "  Math.round(b.right - s.right)];})()")
            print("  layout: field h=%s w=%s | box w=%s pos=%s | '+' dentro "
                  "L=%s R=%s" % tuple(lay))
            checks += [
                ("la caja llena el campo y no colapsa",
                 lay[0] > 30 and abs(lay[2] - lay[1]) <= 2
                 and lay[3] != "absolute"),
                ("el '+' queda dentro de la caja", lay[4] >= 0 and lay[5] >= 0),
            ]

            # escribir antes, pegar bloque grande, escribir despues
            await js("box.value=''; box.dispatchEvent(new Event('input'));"
                     " box.focus()")
            await js("%s('before ')" % TYPE)
            await js("%s(%s)" % (PASTE_TEXT, json.dumps(BIG)))
            await js("%s(' after')" % TYPE)
            chip = await js("(() => {"
                            " const c = document.querySelector('#box .chip');"
                            " if(!c) return null;"
                            " const cs = getComputedStyle(c);"
                            " return [document.querySelectorAll('#box .chip')"
                            ".length, c.textContent, cs.fontWeight,"
                            "  c.getAttribute('contenteditable'),"
                            "  box.value];})()")
            print("  chip: n=%s label=%r peso=%s editable=%r"
                  % (chip[0], chip[1], chip[2], chip[3]))
            print("  value=%r" % chip[4])
            checks += [
                ("un bloque grande se vuelve un chip", chip is not None
                 and chip[0] == 1),
                ("rotulado con el recuento de lineas",
                 "8" in chip[1] and ("líneas" in chip[1] or "lines" in chip[1])),
                ("en negrita (acento del tema)", int(chip[2]) >= 700),
                # el chip es editable (contenteditable=false cierra el teclado en
                # Chrome Android), pero se comporta como unidad: ver borrado abajo
                ("el chip respeta su posicion entre lo escrito",
                 chip[4].startswith("before ") and chip[4].endswith(" after")),
                ("y el envio lo expande a su texto completo, en su sitio",
                 chip[4] == "before " + BIG + " after"),
            ]

            # el envio manda el texto expandido
            await js("window.__sent=[]; ws.send = s => window.__sent.push("
                     "JSON.parse(s));")
            await js("submit()")
            await asyncio.sleep(0.15)
            sent = await js("(window.__sent.find(x => x.type==='prompt')||{})"
                            ".message")
            cleared = await js("[document.querySelectorAll('#box .chip').length,"
                               " box.value, box.classList.contains('ce-blank')]")
            print("  enviado=%r  tras enviar: chips=%s vacio=%s"
                  % (sent, cleared[0], cleared[2]))
            checks += [
                ("el prompt lleva el texto pegado entero",
                 sent == "before " + BIG + " after"),
                ("al enviar se limpia el compositor",
                 cleared[0] == 0 and cleared[1] == "" and cleared[2] is True),
            ]

            # se borra como unidad: pegar y pulsar retroceso justo despues (el
            # caso mas comun) quita el chip entero, no una letra de la etiqueta
            await js("box.value=''; box.dispatchEvent(new Event('input'));"
                     " box.focus()")
            await js("%s('keep ')" % TYPE)
            await js("%s(%s)" % (PASTE_TEXT, json.dumps(BIG)))
            await js("box.dispatchEvent(new InputEvent('beforeinput',"
                     "{inputType:'deleteContentBackward', bubbles:true,"
                     " cancelable:true}))")
            await asyncio.sleep(0.05)
            unit = await js("[document.querySelectorAll('#box .chip').length,"
                            " box.value.replace(/\\u200b/g,'')]")
            print("  borrar-tras-pegar: chips=%s value=%r" % tuple(unit))
            checks.append(("retroceso tras pegar borra el chip entero (unidad)",
                           unit[0] == 0 and unit[1] == "keep "))

            # borrar el chip quita el bloque, deja lo demas
            await js("box.value=''; box.dispatchEvent(new Event('input'));"
                     " box.focus()")
            await js("%s('keep ')" % TYPE)
            await js("%s(%s)" % (PASTE_TEXT, json.dumps(BIG)))
            await js("document.querySelector('#box .chip').remove();"
                     " box.dispatchEvent(new Event('input'))")
            gone = await js("[document.querySelectorAll('#box .chip').length,"
                            " box.value.replace(/\\u200b/g,'')]")
            print("  borrar chip: chips=%s value=%r" % (gone[0], gone[1]))
            checks.append(("borrar el chip quita el bloque y deja lo escrito",
                           gone[0] == 0 and gone[1] == "keep "))

            # un pegado corto va llano, sin chip
            await js("box.value=''; box.dispatchEvent(new Event('input'));"
                     " box.focus()")
            await js("%s(%s)" % (PASTE_TEXT, json.dumps(SMALL)))
            short = await js("[document.querySelectorAll('#box .chip').length,"
                             " box.value]")
            print("  pegado corto: chips=%s value=%r" % tuple(short))
            checks.append(("un pegado corto entra llano, sin chip",
                           short[0] == 0 and short[1] == SMALL))

            # una imagen pegada cae en la fila de miniaturas
            await js("box.value=''; box.dispatchEvent(new Event('input'))")
            await js("clearThumbs()")
            await js(PASTE_IMG)
            await asyncio.sleep(0.3)
            img = await js("[document.querySelectorAll('#thumbs .thumb').length,"
                           " $('#field').classList.contains('hasimg'),"
                           " document.querySelectorAll('#box .chip').length]")
            print("  imagen pegada: thumbs=%s hasimg=%s chips=%s" % tuple(img))
            checks.append(("una imagen pegada va a las miniaturas, no al texto",
                           img[0] == 1 and img[1] is True and img[2] == 0))

            # pegado por teclado (GBoard): llega como beforeinput/insertFromPaste,
            # sin evento 'paste'; tambien debe hacer chip
            await js("box.value=''; box.dispatchEvent(new Event('input'));"
                     " box.focus(); clearThumbs()")
            await js("box.dispatchEvent(new InputEvent('beforeinput',"
                     "{inputType:'insertFromPaste', data:%s,"
                     " bubbles:true, cancelable:true}))" % json.dumps(BIG))
            kb = await js("[document.querySelectorAll('#box .chip').length,"
                          " box.value]")
            print("  pegado por teclado: chips=%s value_ok=%s"
                  % (kb[0], kb[1] == BIG))
            checks.append(("el pegado del teclado tambien hace chip",
                           kb[0] == 1 and kb[1] == BIG))

            # tocar el chip no suelta el foco (no cierra el teclado) y deja el
            # cursor tras el chip: asi se navega texto+chip+texto sin romper
            await js("box.blur();"
                     " document.querySelector('#box .chip').dispatchEvent("
                     "new PointerEvent('pointerdown', {bubbles:true}))")
            await asyncio.sleep(0.05)
            tap = await js("(() => { const s = getSelection();"
                           " const c = document.querySelector('#box .chip');"
                           " const idx = [...box.childNodes].indexOf(c);"
                           " const an = s.anchorNode, ao = s.anchorOffset;"
                           " const after = s.rangeCount > 0 &&"
                           "  ((an === box && ao > idx) || (an !== box &&"
                           "   (c.compareDocumentPosition(an)"
                           "    & Node.DOCUMENT_POSITION_FOLLOWING) > 0));"
                           " return [document.activeElement === box, after];})()")
            print("  tocar chip: foco_box=%s cursor_tras_chip=%s" % tuple(tap))
            checks += [
                ("tocar el chip mantiene el foco (no cierra el teclado)",
                 tap[0] is True),
                ("y deja el cursor tras el chip", tap[1] is True),
            ]

            # Gboard y el paste del sistema no pasan la imagen por el
            # portapapeles legible: insertan un <img> crudo en la caja, sin
            # evento 'paste'. Debe convertirse en adjunto y salir del DOM.
            await js("box.value=''; box.dispatchEvent(new Event('input'));"
                     " clearThumbs(); box.focus()")
            await js("(() => { const i = document.createElement('img');"
                     " i.src = 'data:image/png;base64,%s';"
                     " box.appendChild(i);"
                     " box.dispatchEvent(new Event('input')); })()" % PNG)
            await asyncio.sleep(0.1)
            g1 = await js("[document.querySelectorAll('#thumbs .thumb').length,"
                          " document.querySelectorAll('#box img').length]")
            print("  <img> crudo data:: thumbs=%s imgs_box=%s" % tuple(g1))
            checks.append(("un <img> crudo con src data: se vuelve adjunto",
                           g1[0] == 1 and g1[1] == 0))

            # la otra forma que usan los teclados: src blob: (fetch a base64)
            await js("clearThumbs(); box.focus()")
            await js("(async () => { const b = Uint8Array.from(atob('%s'),"
                     " c => c.charCodeAt(0));"
                     " const u = URL.createObjectURL"
                     " (new Blob([b], {type:'image/png'}));"
                     " const i = document.createElement('img'); i.src = u;"
                     " box.appendChild(i); box.dispatchEvent(new Event('input'));"
                     " })()" % PNG)
            await asyncio.sleep(0.4)
            g2 = await js("[document.querySelectorAll('#thumbs .thumb').length,"
                          " document.querySelectorAll('#box img').length]")
            print("  <img> crudo blob:: thumbs=%s imgs_box=%s" % tuple(g2))
            checks.append(("un <img> crudo con src blob: tambien es adjunto",
                           g2[0] == 1 and g2[1] == 0))

            checks.append(("sin errores de consola", not p.problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
