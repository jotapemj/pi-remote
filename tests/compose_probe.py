"""Boton de enviar, bajar al final, fancybox y reconexion sin saltos."""
import asyncio
import json

from harness import Bridge, FakeProject, Page, ROOT, URL, report

P = str(ROOT)

FILL = """
state = {running:false, waiting:false, alive:true, cwd:%s,
  sessionName:"larga", model:"Qwen3 14B", thinking:"medium", context:null,
  queue:{steering:[],followUp:[]},
  recent:[{name:"pi-remote", path:%s}]};
window.__sent = []; ws.send = s => window.__sent.push(JSON.parse(s));
feed.innerHTML = ""; nodes.clear();
for(let i=1;i<=40;i++)
  render({id:i, kind:"user", text:"mensaje numero " + i});
paint();
main.scrollTo({top:main.scrollHeight,behavior:"instant"});
main.dispatchEvent(new Event("scroll"));
""" % (json.dumps(P), json.dumps(P))

SNAP = """
ws.onmessage({data: JSON.stringify({type:"snapshot", cwd:%s,
  state: state,
  items: Array.from({length:40}, (_,i)=>
    ({id:i+1, kind:"user", text:"mensaje numero " + (i+1)}))})});
""" % json.dumps(P)

async def main():
    with Bridge():
        async with Page(port=9308) as p:
            js, cmd = p.js, p.cmd
            await p.go()
            await js("setLang('es')")
            await js(FILL)
            await asyncio.sleep(0.5)

            checks = []

            send = await js("[!!document.querySelector('#send svg'),"
                            " getComputedStyle($('#send')).borderRadius,"
                            " $('#send').textContent.trim(),"
                            " getComputedStyle($('#send')).width]")
            print("  enviar   : svg=%s radio=%s texto=%r ancho=%s"
                  % tuple(send))
            checks.append(("enviar es un circulo con flecha",
                           send[0] and send[1] == "50%" and send[2] == ""))

            abajo = await js("[$('#godown').classList.contains('on'),"
                             " Math.round(main.scrollTop)]")
            await js("main.scrollTo({top:0,behavior:'instant'}); main.dispatchEvent(new Event('scroll'))")
            await asyncio.sleep(0.45)
            arriba = await js("[$('#godown').classList.contains('on'),"
                              " Number(getComputedStyle($('#godown')).opacity)]")
            print("  al final : boton=%s  arriba: boton=%s opacidad=%s"
                  % (abajo[0], arriba[0], arriba[1]))
            checks.append(("oculto abajo del todo", abajo[0] is False))
            checks.append(("visible si subes", arriba[0] and arriba[1] == 1))

            # reconexion estando arriba: no debe saltar
            antes = await js("Math.round(main.scrollTop)")
            await js(SNAP)
            await asyncio.sleep(0.5)
            despues = await js("Math.round(main.scrollTop)")
            print("  snapshot : scroll %s -> %s" % (antes, despues))
            checks.append(("reconectar no te lleva al final",
                           abs(despues - antes) < 40))

            # y si estabas abajo, sigue abajo
            await js("main.scrollTo({top:main.scrollHeight,behavior:'instant'});"
                     " main.dispatchEvent(new Event('scroll'))")
            await asyncio.sleep(0.3)
            await js(SNAP)
            await asyncio.sleep(0.5)
            fin = await js("[Math.round(main.scrollTop),"
                           " Math.round(main.scrollHeight - main.clientHeight)]")
            print("  estando abajo: %s de %s" % (fin[0], fin[1]))
            checks.append(("si estabas abajo, te quedas abajo",
                           abs(fin[0] - fin[1]) < 40))

            # al llegar MI mensaje, el chat baja hasta el final aunque
            # estuviera arriba (para verlo entero, no a medias)
            await js("main.scrollTo({top:0,behavior:'instant'});"
                     " main.dispatchEvent(new Event('scroll'))")
            await asyncio.sleep(0.3)
            await js("ws.onmessage({data: JSON.stringify({type:'item',"
                     " item:{id:99, kind:'user', text:'nuevo mio'}})})")
            await asyncio.sleep(0.35)
            mine = await js("[Math.round(main.scrollHeight - main.scrollTop"
                            " - main.clientHeight),"
                            " !!nodes.get(99)]")
            print("  tras enviar yo: faltan %s px, pintado=%s" % tuple(mine))
            checks.append(("mi mensaje me lleva al final",
                           mine[0] < 40 and mine[1] is True))

            # el boton baja
            await js("main.scrollTo({top:0,behavior:'instant'}); $('#godown').click()")
            await asyncio.sleep(1.0)
            bajado = await js("Math.round(main.scrollHeight - main.scrollTop"
                              " - main.clientHeight)")
            print("  tras pulsar bajar: faltan %s px" % bajado)
            checks.append(("el boton baja al final", bajado < 40))

            # popup flotante anclado, no dialog ni bottom sheet
            await js("openRail(); projMenu($('#rail'), state.recent[0])")
            await asyncio.sleep(0.4)
            fancy = await js("[!!document.querySelector('.ctxpop'),"
                             " $('#modal').classList.contains('open'),"
                             " $('#sheet').classList.contains('open'),"
                             " document.querySelectorAll('.ctxrow')"
                             ".length]")
            print("  menu: popup=%s modal=%s sheet=%s filas=%s" % tuple(fancy))
            checks.append(("el menu es un popup, no un dialogo",
                           fancy[0] is True and fancy[1] is False
                           and fancy[2] is False and fancy[3] == 2))

            await js("closeCtxPop();"
                     " sessMenu($('#rail'), 'X', {label:'s', path:'y.jsonl'})")
            await asyncio.sleep(0.4)
            sm = await js("[document.querySelectorAll('.ctxrow').length,"
                          " !!document.querySelector('.ctxrow.bad')]")
            print("  menu de sesion: filas=%s con una en rojo=%s" % tuple(sm))
            checks.append(("la sesion ofrece abrir y quitar",
                           sm[0] == 2 and sm[1] is True))
            await js("closeCtxPop()")

            # los mensajes largos del usuario se pliegan; los cortos no
            longtext = " ".join(["palabra%d" % i for i in range(90)])
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:1, kind:'user', text:'corto, una linea'});"
                     " render({id:2, kind:'user', text:%s}); paint();"
                     % json.dumps(longtext))
            await asyncio.sleep(0.3)
            rot = lambda m: m[1]  # el signo del segundo termino de la matriz
            pre = await js("(() => {"
                           " const b = [...document.querySelectorAll("
                           "'.blk-you')];"
                           " const long = b.find(x =>"
                           " x.classList.contains('foldable'));"
                           " return [b[0].classList.contains('foldable'),"
                           "  !!long.querySelector('.ufold'),"
                           "  Math.round(long.querySelector('.utext')"
                           ".getBoundingClientRect().height),"
                           "  getComputedStyle(long.querySelector('.ufold .i'))"
                           ".transform];})()")
            print("  plegable: corto=%s chevron=%s alto=%s rot(exp)=%s"
                  % tuple(pre))
            # ^ expandido = rotate(-90) => segundo termino de la matriz negativo
            await js("foldToggle(document.querySelector('.blk-you.foldable'))")
            await asyncio.sleep(0.45)
            post = await js("(() => { const long ="
                            " document.querySelector('.blk-you.foldable');"
                            " return [long.classList.contains('folded'),"
                            "  Math.round(long.querySelector('.utext')"
                            ".getBoundingClientRect().height),"
                            "  getComputedStyle(long.querySelector('.ufold .i'))"
                            ".transform];})()")
            print("  al plegar: folded=%s alto=%s rot(fold)=%s" % tuple(post))
            checks += [
                ("el mensaje corto no es plegable", pre[0] is False),
                ("el largo tiene chevron", pre[1] is True),
                ("expandido el chevron apunta arriba (^)",
                 "0, -1, 1, 0" in pre[3]),
                ("plegar recorta la altura",
                 post[1] < pre[2] and post[0] is True),
                ("plegado el chevron apunta abajo (v)",
                 "0, 1, -1, 0" in post[2]),
            ]

            # el boton de enviar gira un spinner mientras el mensaje se manda
            await js("state.cwd='C:/x'; state.running=false; paint();"
                     " window.__s2=[]; ws.send = x => window.__s2.push(x);"
                     " box.value='hola'; submit()")
            await asyncio.sleep(0.15)
            spin = await js("[$('#send').classList.contains('sending'),"
                            " !!$('#send .sspin'),"
                            " Number(getComputedStyle($('#send .wait')).opacity)"
                            " > 0.5]")
            print("  al enviar: sending=%s spinner=%s visible=%s" % tuple(spin))
            checks += [
                ("enviar muestra un spinner en el boton",
                 spin[0] is True and spin[1] is True and spin[2] is True),
            ]

            # la barra de contexto: aparece con el turno, se queda, y al
            # aparecer lleva el chat al final para no tapar el mensaje
            await js("""
              state.running=false; state.context=null; barShown=false;
              feed.innerHTML=''; nodes.clear();
              for(let i=0;i<30;i++) render({id:i,kind:'user',text:'m'+i});
              paint(); main.scrollTop = main.scrollHeight - 300;
            """)
            await asyncio.sleep(0.2)
            barIdle = await js("$('#readout').hidden")
            await js("state.running=true;"
                     " state.context={percent:40,tokens:5,window:100}; paint()")
            await asyncio.sleep(0.25)
            barOn = await js("[$('#readout').hidden,"
                             " Math.round(main.scrollHeight - main.scrollTop"
                             " - main.clientHeight)]")
            await js("state.running=false; paint()")
            await asyncio.sleep(0.15)
            barStays = await js("$('#readout').hidden")
            await js("ws.onmessage({data: JSON.stringify({type:'cleared'})})")
            await asyncio.sleep(0.15)
            barGone = await js("$('#readout').hidden")
            print("  barra: idle=%s aparece=%s(faltan %s) queda=%s cleared=%s"
                  % (barIdle, barOn[0], barOn[1], barStays, barGone))
            checks += [
                ("la barra no esta antes del primer turno", barIdle is True),
                ("aparece con el turno y baja el chat al final",
                 barOn[0] is False and barOn[1] < 40),
                ("una vez aparece, se queda al terminar", barStays is False),
                ("en una sesion nueva se esconde de nuevo", barGone is True),
            ]

            # abrir un dialogo con el teclado abierto lo cierra (blur del
            # compositor), o el modal centrado saldria desplazado (/restart)
            await js("box.focus()")
            focused = await js("document.activeElement === box")
            await js("confirmModal('x', '', ()=>{})")
            blurred = await js("document.activeElement !== box")
            await js("closeModal()")
            print("  dialogo: foco antes=%s -> tras abrir=%s"
                   % (focused, not blurred))
            checks.append(("abrir un dialogo cierra el teclado (blur del compositor)",
                           focused is True and blurred is True))

            return report(checks)

raise SystemExit(asyncio.run(main()))
