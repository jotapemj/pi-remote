"""Abort agresivo. Una herramienta de extension que ignora la senal de
abortar (ctx_execute de context-mode) deja a pi esperando: el stop no para
nada. Con el modo agresivo activo, si el turno sigue colgado unos segundos
despues del stop, el puente mata los procesos del arbol de pi creados desde
que empezo la herramienta. Tolerante: un stop que asienta solo, o sin
herramienta en marcha, no mata nada. Contra fake_pi: `hangtool` lanza un
hijo e ignora el abort; `slowtool` lo respeta.
"""
import asyncio
import json
import os
import subprocess
import sys

from harness import Bridge, FakeProject, Page, report

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pi_web_bridge as B  # noqa: E402


def alive(pid):
    return any(r[0] == pid for r in B._process_table())


def reap(pid):
    if pid and alive(pid):
        subprocess.run(["taskkill", "/F", "/PID", str(pid)]
                       if os.name == "nt" else ["kill", "-9", str(pid)],
                       capture_output=True)


async def until(p, expr, timeout=10.0, step=0.1):
    for _ in range(int(timeout / step)):
        if await p.js(expr):
            return True
        await asyncio.sleep(step)
    return False


CHILD = """(() => { const it = [...nodes.values()].map(e => e.__item)
  .filter(i => i && i.kind === 'tool' && i.args && i.args.pid).pop();
  return it ? it.args.pid : null; })()"""
KILLED = ("[...document.querySelectorAll('.note')]"
          ".some(e => /aggressive abort/i.test(e.textContent))")


async def scenario(p, text, aggressive, wait):
    """Lanza un turno, pulsa stop y devuelve (hijo, vivo, running, nota)."""
    await p.js("feed.innerHTML=''; nodes.clear()")
    await p.js("send({type:'prompt', message:%s})" % json.dumps(text))
    child = None
    if text != "stopme":
        await until(p, CHILD + " !== null")
        child = await p.js(CHILD)
    else:
        await until(p, "state.running === true")
    await asyncio.sleep(0.3)
    await p.js("send({type:'abort', aggressive:%s})"
               % ("true" if aggressive else "false"))
    await asyncio.sleep(wait)
    return (child, bool(child) and alive(child),
            await p.js("state.running"), await p.js(KILLED))


async def main():
    checks = []
    # ventana de gracia corta: la real es 5 s
    with Bridge(extra={"PI_AGGR_GRACE": "1.5"}), FakeProject() as proj:
        async with Page() as p:
            await p.go()
            await asyncio.sleep(0.8)
            await p.js("setLang('en'); send({type:'open_project', path:%s})"
                       % json.dumps(proj.path))
            await until(p, "state.running === false")
            await asyncio.sleep(1.2)

            # 1. sin modo agresivo: el stop no para una herramienta colgada
            c1, alive1, run1, note1 = await scenario(p, "hangtool", False, 3.5)
            print("  sin agresivo:", c1, alive1, run1, note1)
            checks.append(("sin el modo: la herramienta colgada sigue viva y "
                           "el turno no asienta",
                           alive1 and run1 is True and not note1))
            reap(c1)                      # soltarla a mano para seguir
            await until(p, "state.running === false")

            # 2. con modo agresivo: mata lo que arranco y el turno asienta
            c2, alive2, run2, note2 = await scenario(p, "hangtool", True, 5.0)
            print("  agresivo:", c2, alive2, run2, note2)
            checks += [
                ("con el modo: mata el proceso de la herramienta",
                 c2 and not alive2),
                ("el turno asienta y el chat queda libre", run2 is False),
                ("y lo dice en una nota", note2),
            ]
            reap(c2)

            # 3. tolerante: una herramienta que si para no se toca
            c3, alive3, run3, note3 = await scenario(p, "slowtool", True, 3.5)
            print("  herramienta que para:", c3, alive3, run3, note3)
            checks.append(("herramienta que respeta el stop: nada que matar, "
                           "sin nota", run3 is False and not note3))
            reap(c3)

            # 4. tolerante: sin herramienta en marcha, stop normal
            _, _, run4, note4 = await scenario(p, "stopme", True, 3.0)
            checks.append(("stop sin herramienta: nada que matar, sin nota",
                           run4 is False and not note4))

            # 5. la card: se activa solo tras confirmar
            await p.js("localStorage.removeItem('pi.aggrAbort');"
                       " setAggrAbort(false); menuSheet(); goPage('functions')")
            await asyncio.sleep(0.5)
            ui = await p.js("""(() => {
              const card = [...document.querySelectorAll('#sheetBody .fcard')]
                .find(c => /Aggressive abort/.test(c.textContent));
              const sw = card.querySelector('.sw');
              sw.click();
              const dlg = {title: $('#modalTitle').textContent,
                           ok: $('#modalOk').textContent,
                           no: $('#modalNo').textContent,
                           body: $('#modalBody').textContent};
              $('#modalNo').click();
              const afterCancel = [sw.getAttribute('aria-checked'), aggrAbort];
              sw.click(); $('#modalOk').click();
              const afterOk = [sw.getAttribute('aria-checked'), aggrAbort,
                               localStorage.getItem('pi.aggrAbort')];
              sw.click();
              const afterOff = [sw.getAttribute('aria-checked'), aggrAbort,
                                $('#modal').classList.contains('open')];
              return {dlg, afterCancel, afterOk, afterOff}; })()""")
            print("  card:", ui)
            checks += [
                ("card en Functions con dialogo Cancel / Activate",
                 ui["dlg"]["title"] == "Aggressive abort"
                 and ui["dlg"]["ok"] == "Activate"
                 and ui["dlg"]["no"] == "cancel"
                 and ui["dlg"]["body"].endswith("ignores the stop.")),
                ("cancelar lo deja apagado", ui["afterCancel"] == ["false", False]),
                ("activar lo enciende y lo recuerda",
                 ui["afterOk"] == ["true", True, "1"]),
                ("apagar es directo, sin dialogo",
                 ui["afterOff"] == ["false", False, False]),
            ]
            # el stop lleva la bandera
            flag = await p.js("""(() => { const sent = [];
              const s0 = ws.send.bind(ws);
              ws.send = x => { sent.push(JSON.parse(x)); };
              setAggrAbort(true); state.running = true;
              $('#send').classList.add('halting'); $('#send').click();
              ws.send = s0; state.running = false;
              return sent.filter(o => o.type === 'abort'); })()""")
            checks.append(("el stop manda aggressive con el modo activo",
                           bool(flag) and flag[0].get("aggressive") is True))
            # /abort de la paleta: el mismo stop que el boton
            pal = await p.js("""(() => { const sent = [];
              const s0 = ws.send.bind(ws);
              ws.send = x => { sent.push(JSON.parse(x)); };
              setAggrAbort(true); CMDS.find(c => c.n === 'abort').run();
              setAggrAbort(false); CMDS.find(c => c.n === 'abort').run();
              ws.send = s0;
              return sent.filter(o => o.type === 'abort')
                .map(o => o.aggressive); })()""")
            checks.append(("/abort de la paleta sigue el interruptor",
                           pal == [True, False]))
            await p.js("setAggrAbort(false)")
    return checks


raise SystemExit(report(asyncio.run(main())))
