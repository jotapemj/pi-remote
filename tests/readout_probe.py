"""Palabra junto al cursor, medidor, copiar codigo, nombre e idioma."""
import asyncio
import json

from harness import Bridge, FakeProject, Page, ROOT, URL, report

SEED = r"""
state = {running:true, waiting:false, alive:true, cwd:"C:\\p",
  sessionName:"nombre viejo", model:"Qwen3 14B", thinking:"medium",
  startedAt: Date.now()/1000 - 5,
  context:{percent:56.789123, tokens:56320, window:131072},
  queue:{steering:[],followUp:[]}, recent:[]};
window.__sent = []; ws.send = s => window.__sent.push(JSON.parse(s));
feed.innerHTML = ""; nodes.clear();
render({id:1, kind:"assistant", streaming:true,
        text:"Mirando esto.\n\n```py\nx = 5 < 6\nprint(x)\n```\n"});
curWord = "Cacharreando";
paint(); showWord(false);
"""

async def main():
    with Bridge():
        async with Page(port=9310) as p:
            js, cmd = p.js, p.cmd
            await p.go()
            await js("setLang('es')")
            await js(SEED)
            await asyncio.sleep(0.6)

            checks = []

            w = await js("[(feed.querySelector('.wordi')||{}).textContent,"
                         " !!feed.querySelector('.cursor'),"
                         " !!document.querySelector('#readout .wordi'),"
                         " getComputedStyle(feed.querySelector('.cursor'))"
                         ".animationName,"
                         " (feed.querySelector('.elapsed')||{}).textContent,"
                         " getComputedStyle(feed.querySelector('.elapsed'))"
                         ".color]")
            print("  palabra=%r cursor=%s en la barra=%s animacion=%s"
                  % tuple(w[:4]))
            print("  segundos=%r color=%s" % (w[4], w[5]))
            checks.append(("la palabra va junto al cursor",
                           w[0] == "Cacharreando\u2026" and w[1]
                           and not w[2]))
            checks.append(("los segundos van a su lado, apagados",
                           bool(w[4]) and w[4].endswith("s")
                           and w[5] != w[3]))
            checks.append(("el cursor late suave", w[3] == "pulse"))

            await js("curWord = 'Soldando'; showWord(true)")
            await asyncio.sleep(0.08)
            mid = await js("Number(getComputedStyle("
                           "feed.querySelector('.wordi')).opacity)")
            await asyncio.sleep(0.5)
            end = await js("(feed.querySelector('.wordi')||{}).textContent")
            print("  al rotar: opacidad a 80ms=%s -> %r" % (mid, end))
            checks.append(("la palabra se funde al cambiar",
                           0 <= mid < 1 and end == "Soldando\u2026"))

            halt = await js("[$('#send').classList.contains('halting'),"
                            " !!$('#send .halt svg'),"
                            " Number(getComputedStyle($('#send .halt'))"
                            ".opacity),"
                            " Number(getComputedStyle($('#send .go'))"
                            ".opacity),"
                            " !!document.querySelector('#stopBtn'),"
                            " getComputedStyle($('#readout'))"
                            ".justifyContent]")
            print("  parar: %s" % halt)
            checks += [
                ("enviar se vuelve parar mientras trabaja",
                 halt[0] is True and halt[1] is True),
                ("con fundido entre los dos iconos",
                 halt[2] == 1 and halt[3] == 0),
                ("y ya no hay boton de parar suelto", halt[4] is False),
                ("la barra de contexto va a la derecha",
                 halt[5] == "flex-end"),
            ]

            await js("for(let i=0;i<24;i++)"
                     " render({id:900+i, kind:'tool', name:'bash',"
                     "  status:'done', args:{command:'ls'}, output:'x'})")
            await asyncio.sleep(0.3)
            await js("main.scrollTop = 0")      # el salto necesita su turno
            await asyncio.sleep(0.3)
            over = await js("(() => { goDown();"
                            " const d = $('#godown').getBoundingClientRect();"
                            " const b = $('#bar').getBoundingClientRect();"
                            " return [$('#godown').classList.contains('on'),"
                            " Math.round(d.bottom), Math.round(b.top),"
                            " Math.round(d.bottom - b.top)];})()")
            print("  bajar: visible=%s abajo=%s barra=%s solape=%s"
                  % tuple(over))
            checks += [
                ("el boton de bajar aparece al subir", over[0] is True),
                ("y no se monta sobre la barra de contexto",
                 over[1] <= over[2]),
            ]

            ctx = await js("[$('#bar').lastElementChild.textContent,"
                           " $('#bar').firstElementChild.style.width,"
                           " $('#bar').className,"
                           " getComputedStyle($('#bar')).borderRadius]")
            print("  medidor: %r ancho=%s clases=%r radio=%s" % tuple(ctx))
            checks.append(("dos decimales", "56.79%" in ctx[0]))
            checks.append(("contexto en k separado", "56k/131k" in ctx[0]))
            checks.append(("el relleno sigue al porcentaje",
                           ctx[1].startswith("56.78")))
            checks.append(("extremos redondeados", ctx[3] == "11px"))

            cp = await js("[document.querySelectorAll('.cwrap .copyb').length,"
                          " !!document.querySelector('.copyb svg')]")
            await js("document.querySelector('.copyb').click()")
            await asyncio.sleep(0.5)
            done = await js("[document.querySelector('.copyb')"
                            ".classList.contains('done'),"
                            " !!document.querySelector('.copyb svg')]")
            clip = await js("navigator.clipboard.readText()"
                            ".then(t=>t, e=>'no legible: ' + e.name)")
            print("  copiar: botones=%s icono=%s | tras pulsar done=%s"
                  % (cp[0], cp[1], done[0]))
            checks.append(("boton copiar con icono", cp[0] == 1 and cp[1]))
            print("  portapapeles:", repr(clip)[:50])
            # headless no deja tocar el portapapeles ni con permisos:
            # lo comprobable es que responde por los dos caminos
            avisó = await js("[...feed.querySelectorAll('.note')]"
                             ".some(n=>/copiar|copy/.test(n.textContent))")
            print("  aviso al fallar:", avisó)
            checks.append(("copiar responde de un modo u otro",
                           (done[0] is True and done[1]) or avisó is True))
            if isinstance(clip, str) and not clip.startswith("no legible"):
                checks.append(("copia el codigo entero",
                               "x = 5 < 6" in clip and "print(x)" in clip))

            # el nombre se funde
            await js("title('nombre nuevo')")
            await asyncio.sleep(0.09)
            fading = await js("[Number(getComputedStyle("
                              "$('#title').firstElementChild).opacity),"
                              " $('#title').textContent]")
            await asyncio.sleep(0.5)
            after = await js("$('#title').textContent")
            print("  nombre: a 90ms opacidad=%s %r -> %r"
                  % (fading[0], fading[1][:22], after[:26]))
            checks.append(("el nombre viejo se desvanece", fading[0] < 1))
            checks.append(("y entra el nuevo", "nombre nuevo" in after))

            # el menu navega por paginas
            await js("menuSheet()")
            await asyncio.sleep(0.4)
            root = await js("[$('#sheetTitle').textContent,"
                            " $('#sheetBack').hidden,"
                            " document.querySelectorAll('#sheetBody .pick')"
                            ".length]")
            await js("turnTo('appearance', 1)")
            await asyncio.sleep(0.12)
            moving = await js("(() => {const b = $('#sheetBody');"
                              " return [Math.round(new DOMMatrixReadOnly("
                              "getComputedStyle(b).transform).m41),"
                              " Number(getComputedStyle(b).opacity)];})()")
            await asyncio.sleep(0.6)
            inside = await js("[$('#sheetTitle').textContent,"
                              " $('#sheetBack').hidden,"
                              " !!document.querySelector('#sheetBody .sizecard'),"
                              " !!document.querySelector('#sheetBack svg')]")
            await js("turnTo('language', 1)")
            await asyncio.sleep(0.7)
            langs = await js("[...document.querySelectorAll('#sheetBody .pick')]"
                             ".map(b=>b.textContent)")
            await js("[...document.querySelectorAll('#sheetBody .pick')]"
                     ".find(b=>/English/.test(b.textContent)).click()")
            await asyncio.sleep(0.7)
            after = await js("[lang(), $('#sheetTitle').textContent,"
                             " $('#sheetBack').hidden]")
            print("  raiz    : %r back oculto=%s tarjetas=%s" % tuple(root))
            print("  entrando: desplazado %s opacidad %s" % tuple(moving))
            print("  dentro  : %r back=%s slider=%s flecha=%s" % tuple(inside))
            print("  idiomas : %s -> tras elegir: %r, vuelve a %r"
                  % (langs, after[0], after[1]))

            checks += [
                ("la raiz no trae flecha de volver", root[1] is True),
                ("entra deslizandose y con fundido",
                 moving[0] != 0 and moving[1] < 1),
                ("apariencia trae el tema y el tamano",
                 inside[0].lower() == "apariencia" and inside[2] is True),
                ("y una flecha para volver",
                 inside[1] is False and inside[3] is True),
                ("el idioma es otra pagina", len(langs) == 2),
                ("elegirlo aplica y vuelve al menu",
                 after[0] == "en" and after[1].lower() == "menu"
                 and after[2] is True),
            ]

            # el tema se previsualiza al tocarlo, pero pide Aceptar
            await js("closeModal(); setTheme('dark'); menuSheet(); themeModal()")
            await asyncio.sleep(0.4)
            rows = await js("[...document.querySelectorAll('#modalBody .mrow')]"
                            ".map(b=>b.dataset.t)")
            await js("[...document.querySelectorAll('#modalBody .mrow')]"
                     ".find(b=>b.dataset.t==='klaude').click()")
            await asyncio.sleep(0.3)
            preview = await js("[document.documentElement.dataset.theme,"
                               " $('#modal').classList.contains('open'),"
                               " localStorage.getItem('pi.theme')]")
            await js("$('#modalNo').click()")
            await asyncio.sleep(0.4)
            cancelled = await js("[document.documentElement.dataset.theme,"
                                 " $('#modal').classList.contains('open')]")
            await js("menuSheet(); themeModal()")
            await asyncio.sleep(0.3)
            await js("[...document.querySelectorAll('#modalBody .mrow')]"
                     ".find(b=>b.dataset.t==='klaude').click();"
                     " $('#modalOk').click()")
            await asyncio.sleep(0.4)
            accepted = await js("[document.documentElement.dataset.theme,"
                                " localStorage.getItem('pi.theme'),"
                                " getComputedStyle(document.body)"
                                ".backgroundColor]")
            print("  temas: %s" % rows)
            print("  al tocar Klaude: %s abierto=%s guardado=%r"
                  % (preview[0], preview[1], preview[2]))
            print("  al cancelar    : %s" % cancelled[0])
            print("  al aceptar     : %s guardado=%r fondo=%s"
                  % (accepted[0], accepted[1], accepted[2]))

            # el tamano del texto
            await js("closeModal(); menuSheet()")
            await asyncio.sleep(0.3)
            await js("turnTo('appearance', 1)")   # el slider vive ahi
            await asyncio.sleep(0.7)
            size = await js("(() => {"
                            " const i = document.querySelector('.track input');"
                            " i.value = 6; i.dispatchEvent(new Event('input'));"
                            " return [getComputedStyle(document.documentElement)"
                            ".getPropertyValue('--chat-size').trim(),"
                            " localStorage.getItem('pi.size'),"
                            " document.querySelectorAll('.fsize .a').length];"
                            "})()")
            print("  tamano al 6: %s guardado=%r letras=%s" % tuple(size))

            checks += [
                ("los cinco temas, con las dos variantes Klaude",
                 rows == ["auto", "light", "dark", "klaude",
                          "klaude-light"]),
                ("tocar uno lo previsualiza sin cerrar ni guardar",
                 preview[0] == "klaude" and preview[1] is True
                 and preview[2] == "dark"),
                ("cancelar lo deshace",
                 cancelled[0] == "dark" and cancelled[1] is False),
                ("aceptar lo aplica y lo guarda",
                 accepted[0] == "klaude" and accepted[1] == "klaude"
                 and "21, 21, 21" in accepted[2]),
                ("el tamano del texto se aplica y se guarda",
                 size[0] == "19px" and size[1] == "6"),
                ("con una A a cada lado", size[2] == 2),
            ]

            kb = await js("[getComputedStyle(document.querySelector('footer'))"
                          ".paddingBottom,"
                          " getComputedStyle(document.documentElement)"
                          ".getPropertyValue('--kb').trim()]")
            print("  teclado: padding=%s --kb=%r" % tuple(kb))
            checks.append(("el compositor reserva sitio al teclado",
                           kb[1] != ""))

            return report(checks)

raise SystemExit(asyncio.run(main()))
