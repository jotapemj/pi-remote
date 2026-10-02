"""/bash del usuario: la tarjeta de comando aparece AL LANZARLO, en marcha y
con el comando, y se rellena al terminar. La ejecucion no cambia: la hace pi
(guarda la salida en el contexto del agente) y por RPC solo responde al
final; antes la tarjeta tambien esperaba al final para existir, y mientras
el comando corria no se veia nada.
"""
import asyncio
import json

from harness import Bridge, FakeProject, Page, report


async def until(p, expr, timeout=10.0, step=0.1):
    for _ in range(int(timeout / step)):
        if await p.js(expr):
            return True
        await asyncio.sleep(step)
    return False


ROWS = """[...nodes.values()].map(e => e.__item)
  .filter(i => i && i.kind === 'tool' && i.name === 'bash (direct)')
  .map(i => ({cmd: i.args && i.args.command, status: i.status,
              out: i.output || ''}))"""


async def main():
    checks = []
    with Bridge(), FakeProject() as proj:
        async with Page() as p:
            await p.go()
            await asyncio.sleep(0.8)
            await p.js("send({type:'open_project', path:%s})"
                       % json.dumps(proj.path))
            await until(p, "state.running === false")
            await asyncio.sleep(1.0)
            await p.js("feed.innerHTML=''; nodes.clear();"
                       " CMDS.find(c => c.n === 'bash').run('python deploy.py')")
            await asyncio.sleep(0.5)
            early = await p.js(ROWS)
            shown = await p.js("""(() => { const d = [...document.querySelectorAll(
              '#feed .tool')].pop(); return d ? {s: d.dataset.s,
              head: d.querySelector('summary').textContent} : null; })()""")
            await until(p, ROWS + ".some(r => r.status !== 'running')")
            late = await p.js(ROWS)
            print("  al lanzar:", early, shown, "| al terminar:", late)
            checks += [
                ("al lanzar ya hay tarjeta, en marcha, con el comando",
                 early == [{"cmd": "python deploy.py", "status": "running",
                            "out": ""}]),
                ("se ve como las de pi: punto en marcha y el comando",
                 shown and shown["s"] == "running"
                 and "python deploy.py" in shown["head"]),
                ("al terminar, la MISMA tarjeta se rellena (no una nueva)",
                 len(late) == 1 and late[0]["status"] == "done"
                 and "hecho" in late[0]["out"]),
            ]

            # dos seguidos: cada respuesta rellena la suya, en orden
            await p.js("feed.innerHTML=''; nodes.clear();"
                       " CMDS.find(c => c.n === 'bash').run('uno');"
                       " CMDS.find(c => c.n === 'bash').run('dos fail')")
            await until(p, ROWS + ".every(r => r.status !== 'running')"
                        " && " + ROWS + ".length === 2", timeout=12)
            two = await p.js(ROWS)
            print("  dos:", two)
            checks += [
                ("dos seguidos: dos tarjetas, cada una con lo suyo",
                 [(r["cmd"], r["status"]) for r in two]
                 == [("uno", "done"), ("dos fail", "error")]
                 and "$ uno" in two[0]["out"]
                 and "$ dos fail" in two[1]["out"]),
            ]
    return checks


raise SystemExit(report(asyncio.run(main())))
