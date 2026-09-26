"""Telon de /restart: no se retira con el primer snapshot del puente nuevo,
sino cuando el historial del proyecto ya esta cargado (state.loading).

Backend: abrir proyecto pone loading=True y el snapshot del historial lo
devuelve a False. Cliente: con el telon de reinicio puesto, un snapshot con
loading=True lo deja; uno con loading=False lo retira.
"""
import asyncio
import json

from harness import Bridge, FakeProject, Page, report


async def until(p, expr, timeout=8.0, step=0.1):
    for _ in range(int(timeout / step)):
        if await p.js(expr):
            return True
        await asyncio.sleep(step)
    return False


async def main():
    checks = []
    with Bridge(), FakeProject() as proj:
        async with Page(port=9412) as p:
            js = p.js
            await p.go()
            await asyncio.sleep(0.6)

            # ---- backend: el flag viaja en el estado ----
            await js("""window.__ld = [];
              const _om = ws.onmessage;
              ws.onmessage = e => { const m = JSON.parse(e.data);
                if(m.type === 'snapshot' || m.type === 'state')
                  __ld.push([m.type, !!(m.state && m.state.loading)]);
                _om(e); };""")
            await js("send({type:'open_project', path:%s})"
                     % json.dumps(proj.path))
            await until(p, "__ld.some(x => x[0]==='snapshot' && !x[1])"
                           " && __ld.some(x => x[1])")
            ld = await js("__ld")
            print("  estados: %s" % ld)
            last_snap = [x for x in ld if x[0] == "snapshot"][-1:]
            checks += [
                ("abrir proyecto marca loading", any(x[1] for x in ld)),
                ("el snapshot del historial lo devuelve a False",
                 last_snap == [["snapshot", False]]),
                ("y el estado queda sin cargar", await js("state.loading")
                 is False),
            ]

            # ---- cliente: el telon espera a loading False ----
            snap = await js("""JSON.stringify({type:'snapshot', items:[],
              cwd: CWD, state: Object.assign({}, state, {loading:true})})""")
            await js("beginRestartOverlay(); showRestartCurtain()")
            await asyncio.sleep(0.2)
            await js("ws.onmessage({data: %s})" % json.dumps(snap))
            await asyncio.sleep(0.4)
            mid = await js("""(()=>{const c=$('#curtain');
              return {rest: c.classList.contains('restarting'),
                gone: c.classList.contains('gone'), mode: restartMode,
                disp: getComputedStyle(c).display};})()""")
            done = snap.replace('"loading":true', '"loading":false')
            await js("ws.onmessage({data: %s})" % json.dumps(done))
            await asyncio.sleep(0.4)
            end = await js("""(()=>{const c=$('#curtain');
              return {rest: c.classList.contains('restarting'),
                gone: c.classList.contains('gone'), mode: restartMode};})()""")
            print("  telon con loading: %s  sin loading: %s" % (mid, end))
            checks += [
                ("con el historial en camino, el telon sigue",
                 mid["rest"] and not mid["gone"] and mid["mode"]
                 and mid["disp"] != "none"),
                ("cargado, el telon se retira",
                 end["gone"] and not end["rest"] and not end["mode"]),
            ]

            # ---- todo de vuelta: historial Y titulo Y modelo ----
            # con el historial listo pero el titulo aun en skeleton, sigue
            # (como en un reinicio real: el snapshot llega sin nombre y el
            # nombre llega despues, con el get_state)
            noname = await js("""JSON.stringify({type:'snapshot', items:[],
              cwd: CWD, state: Object.assign({}, state,
                {loading:false, sessionName:null})})""")
            await js("beginRestartOverlay(); showRestartCurtain();"
                     " sessLoading = true")
            await js("ws.onmessage({data: %s})" % json.dumps(noname))
            await asyncio.sleep(0.5)
            wait_title = await js("$('#curtain').classList.contains('restarting')")
            await js("""ws.onmessage({data: JSON.stringify({type:'state',
              state: Object.assign({}, state, {sessionName:'vuelta'})})})""")
            await asyncio.sleep(0.5)
            after_title = await js("$('#curtain').classList.contains('gone')")
            checks += [
                ("con el titulo sin resolver, el telon espera", wait_title),
                ("resuelto el titulo, se retira", after_title),
            ]

            # ---- bloqueo desde que se confirma /restart ----
            # la tarea real no se lanza: el puente del harness no la tiene
            # configurada y contesta, lo que interesa aqui es el cliente
            await js("restartLock(true)")
            lk = await js("""(()=>{
              const el = document.elementFromPoint(innerWidth/2, innerHeight/2);
              const ev = new KeyboardEvent('keydown', {key:'a', cancelable:true});
              document.dispatchEvent(ev);
              return {top: el && el.id, key: ev.defaultPrevented,
                      z: +getComputedStyle($('#rlock')).zIndex};})()""")
            # el puente dice que no va a reiniciar: fuera el bloqueo
            await js("""onMsgNote = (k) => ws.onmessage({data: JSON.stringify(
              {type:'item', item:{id: 99990, kind:'note', level:'warn',
               key:k, text:k}})}); onMsgNote('read_only')""")
            await asyncio.sleep(0.2)
            gone = await js("!$('#rlock')")
            print("  bloqueo: %s  liberado tras rechazo=%s" % (lk, gone))
            checks += [
                ("al confirmar, una capa se come los toques",
                 lk["top"] == "rlock" and lk["z"] == 59),
                ("y las teclas", lk["key"] is True),
                ("si el puente no va a reiniciar, se libera", gone),
            ]
    return checks


raise SystemExit(report(asyncio.run(main())))
