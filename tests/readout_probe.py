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

            w = await js("[($('#rword')||{}).textContent,"
                         " !!feed.querySelector('.cursor'),"
                         " ($('#rsecs')||{}).textContent,"
                         " $('#readout').classList.contains('thinking'),"
                         " Number(getComputedStyle($('#rword')).opacity),"
                         " !!feed.querySelector('.wordi')]")
            print("  palabra=%r cursor=%s" % (w[0], w[1]))
            print("  segundos=%r pensando=%s opacidad=%s en_burbuja=%s"
                  % (w[2], w[3], w[4], w[5]))
            checks += [
                ("la palabra esta en la barra, no en la burbuja",
                 w[0] == "Cacharreando\u2026" and w[5] is False),
                ("ya no hay cursor parpadeante en la burbuja", w[1] is False),
                ("los segundos van en la barra",
                 bool(w[2]) and w[2].endswith("s")),
                ("mientras piensa, la palabra se ve",
                 w[3] is True and w[4] > 0.5),
            ]

            # al teclear (llega un delta) la palabra se esconde
            await js("ws.onmessage({data: JSON.stringify("
                     "{type:'delta', id:1, delta:' mas texto'})})")
            await asyncio.sleep(0.15)   # a mitad del fundido, con colchon
            typing = await js("[$('#readout').classList.contains('thinking'),"
                              " Number(getComputedStyle($('#rword')).opacity)]")
            print("  al teclear: pensando=%s opacidad=%s" % tuple(typing))
            checks.append(("mientras teclea, la palabra desaparece",
                           typing[0] is False and typing[1] < 0.6))

            await js("curWord = 'Soldando'; showWord(true)")
            await asyncio.sleep(0.08)
            mid = await js("Number(getComputedStyle($('#rword')).opacity)")
            await asyncio.sleep(0.5)
            end = await js("($('#rword')||{}).textContent")
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
                 halt[5] == "space-between"),
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
                  % (json.dumps(langs, ensure_ascii=True),
                     after[0], after[1]))

            checks += [
                ("la raiz no trae flecha de volver", root[1] is True),
                ("entra deslizandose y con fundido",
                 moving[0] != 0 and moving[1] < 1),
                ("apariencia trae el tema y el tamano",
                 inside[0].lower() == "apariencia" and inside[2] is True),
                ("y una flecha para volver",
                 inside[1] is False and inside[3] is True),
                ("el idioma es otra pagina con los seis idiomas",
                 len(langs) == 6
                 and all(any(n in b for b in langs)
                         for n in ("English", "Espa\u00f1ol", "Deutsch",
                                   "Fran\u00e7ais", "Portugu\u00eas", "中文"))),
                ("elegirlo aplica y vuelve al menu",
                 after[0] == "en" and after[1].lower() == "menu"
                 and after[2] is True),
            ]

            # familias arriba (por nombre), modo abajo (Auto + claro/oscuro)
            await js("closeModal(); setTheme('pi','dark'); menuSheet(); themeModal()")
            await asyncio.sleep(0.4)
            fams = await js("[...document.querySelectorAll('#modalBody .mrow')]"
                            ".map(b=>b.dataset.fam)")
            footer = await js("[!!document.querySelector('#modalBody .tmode .sw'),"
                              " [...document.querySelectorAll("
                              "'#modalBody .seg button')].map(b=>b.dataset.m)]")
            # tocar una familia (Klaude) la previsualiza en el modo actual (dark)
            await js("[...document.querySelectorAll('#modalBody .mrow')]"
                     ".find(b=>b.dataset.fam==='klaude').click()")
            await asyncio.sleep(0.3)
            preview = await js("[document.documentElement.dataset.theme,"
                               " $('#modal').classList.contains('open'),"
                               " localStorage.getItem('pi.themeFamily')]")
            # el switch Auto deja en disabled el toggle claro/oscuro
            await js("document.querySelector('#modalBody .tmode .sw').click()")
            await asyncio.sleep(0.15)
            autoed = await js("[document.querySelector('#modalBody .tmode .sw')"
                              ".getAttribute('aria-checked'),"
                              " document.querySelector('#modalBody .seg button')"
                              ".disabled,"
                              " document.querySelector('#modalBody .seg')"
                              ".classList.contains('off')]")
            await js("$('#modalNo').click()")
            await asyncio.sleep(0.4)
            cancelled = await js("[document.documentElement.dataset.theme,"
                                 " $('#modal').classList.contains('open')]")
            # de nuevo: Klaude + claro, aceptar -> guarda familia y modo
            await js("menuSheet(); themeModal()")
            await asyncio.sleep(0.3)
            await js("[...document.querySelectorAll('#modalBody .mrow')]"
                     ".find(b=>b.dataset.fam==='klaude').click();"
                     " [...document.querySelectorAll('#modalBody .seg button')]"
                     ".find(b=>b.dataset.m==='light').click();"
                     " $('#modalOk').click()")
            await asyncio.sleep(0.4)
            accepted = await js("[document.documentElement.dataset.theme,"
                                " localStorage.getItem('pi.themeFamily'),"
                                " localStorage.getItem('pi.themeMode')]")
            print("  familias: %s" % fams)
            print("  pie: switch=%s toggle=%s" % (footer[0], footer[1]))
            print("  al tocar Klaude: %s abierto=%s fam=%r"
                  % (preview[0], preview[1], preview[2]))
            print("  auto: checked=%s btn.disabled=%s seg.off=%s" % tuple(autoed))
            print("  al cancelar: %s" % cancelled[0])
            tc = await js("[document.querySelector("
                          "'meta[name=\"theme-color\"]').content.trim()"
                          ".toLowerCase(),"
                          " getComputedStyle(document.documentElement)"
                          ".getPropertyValue('--plate-a').trim().toLowerCase()]")
            print("  barra de estado: %r vs plate-a %r" % (tc[0], tc[1]))
            print("  al aceptar: %s fam=%r modo=%r" % tuple(accepted))

            # bug movil: cerrar sin aceptar (tocar fuera) no debe dejar el
            # tema previsualizado aplicado; se revierte al guardado
            await js("menuSheet(); themeModal();"
                     " [...document.querySelectorAll('#modalBody .mrow')]"
                     ".find(b=>b.dataset.fam==='gemma').click()")
            await asyncio.sleep(0.2)
            await js("closeModal()")           # ni Aceptar ni Cancelar
            await asyncio.sleep(0.3)
            dismissed = await js("[document.documentElement.dataset.theme,"
                                 " localStorage.getItem('pi.themeFamily')]")
            await js("menuSheet(); themeModal()")
            await asyncio.sleep(0.3)
            reopened = await js("document.querySelector('#modalBody .mrow.on')"
                                ".dataset.fam")
            await js("$('#modalNo').click()")
            await asyncio.sleep(0.3)
            print("  cerrar sin aceptar: %s fam=%r  reabre marcada=%r"
                  % (dismissed[0], dismissed[1], reopened))

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
                ("las cuatro familias, por nombre",
                 fams == ["pi", "klaude", "jipiti", "gemma"]),
                ("el pie trae Auto y el toggle claro/oscuro",
                 footer[0] is True and footer[1] == ["light", "dark"]),
                ("la barra de estado sigue al color de la toolbar",
                 tc[0] == tc[1] and tc[0] != ""),
                ("tocar una familia la previsualiza sin cerrar ni guardar",
                 preview[0] == "klaude" and preview[1] is True
                 and preview[2] == "pi"),
                ("Auto deja en disabled el toggle claro/oscuro",
                 autoed[0] == "true" and autoed[1] is True
                 and autoed[2] is True),
                ("cancelar lo deshace",
                 cancelled[0] == "dark" and cancelled[1] is False),
                ("aceptar aplica y guarda familia y modo",
                 accepted[0] == "klaude-light" and accepted[1] == "klaude"
                 and accepted[2] == "light"),
                ("cerrar sin aceptar revierte, no deja el preview aplicado",
                 dismissed[0] == "klaude-light" and dismissed[1] == "klaude"),
                ("y al reabrir marca la familia guardada",
                 reopened == "klaude"),
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
