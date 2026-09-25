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
    return checks


raise SystemExit(report(asyncio.run(main())))
