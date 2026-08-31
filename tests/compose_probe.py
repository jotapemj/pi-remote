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

            # el boton baja
            await js("main.scrollTo({top:0,behavior:'instant'}); $('#godown').click()")
            await asyncio.sleep(1.0)
            bajado = await js("Math.round(main.scrollHeight - main.scrollTop"
                              " - main.clientHeight)")
            print("  tras pulsar bajar: faltan %s px" % bajado)
            checks.append(("el boton baja al final", bajado < 40))

            # fancybox en vez de bottom sheet
            await js("openRail(); projMenu(state.recent[0])")
            await asyncio.sleep(0.4)
            fancy = await js("[$('#modal').classList.contains('open'),"
                             " $('#sheet').classList.contains('open'),"
                             " document.querySelectorAll('#modalBody .mrow')"
                             ".length]")
            print("  long press: modal=%s sheet=%s filas=%s" % tuple(fancy))
            checks.append(("el menu es un dialogo, no un panel",
                           fancy[0] is True and fancy[1] is False
                           and fancy[2] == 2))

            await js("closeModal(); sessMenu('X', {label:'s', path:'y.jsonl'})")
            await asyncio.sleep(0.4)
            sm = await js("[document.querySelectorAll('#modalBody .mrow').length,"
                          " !!document.querySelector('#modalBody .mrow.bad')]")
            print("  menu de sesion: filas=%s con una en rojo=%s" % tuple(sm))
            checks.append(("la sesion ofrece abrir y quitar",
                           sm[0] == 2 and sm[1] is True))

            return report(checks)

raise SystemExit(asyncio.run(main()))
