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


def readers():
    """Los lectores de procesos. Windows se mide de verdad; Linux y macOS
    no se pueden ejecutar aqui: se comprueba su parser con datos falsos."""
    import tempfile
    from pathlib import Path
    checks = []
    if os.name == "nt":
        me = os.getpid()
        nat = {r[0]: r for r in B._proc_table_win()}
        ps = {r[0]: r for r in B._proc_table_powershell()}
        checks.append(("Windows nativo: mismo padre y hora que PowerShell",
                       me in nat and me in ps and nat[me][1] == ps[me][1]
                       and abs(nat[me][2] - ps[me][2]) < 0.01))
    # /proc falso: btime + ticks/hz, y un nombre con espacios y parentesis
    root = Path(tempfile.mkdtemp())
    (root / "stat").write_text("cpu 1 2\nbtime 1000\n", encoding="ascii")
    (root / "42").mkdir()
    fields = ["S", "7"] + ["0"] * 17 + ["500"] + ["0"] * 10
    (root / "42" / "stat").write_text(
        "42 (java (daemon) x) " + " ".join(fields), encoding="utf-8")
    (root / "self").mkdir()
    rows = B._proc_table_linux(str(root), hz=100)
    checks.append(("Linux: /proc parseado (padre, arranque, nombre raro)",
                   rows == [(42, 7, 1005.0, "java (daemon) x")]))
    # ps de macOS: etime en [[dd-]hh:]mm:ss
    real = B.subprocess.run

    class R:
        stdout = ("  10     1       02:05 java\n"
                  "  11    10    01:00:00 kotlin daemon\n"
                  "  12    10  2-00:00:10 old\n")
    B.subprocess.run = lambda *a, **k: R()
    try:
        t0 = B.time.time()
        mac = {r[0]: r for r in B._proc_table_ps()}
    finally:
        B.subprocess.run = real
    checks.append(("macOS: etime a segundos (mm:ss, hh:mm:ss, dd-hh:mm:ss)",
                   abs((t0 - mac[10][2]) - 125) < 2
                   and abs((t0 - mac[11][2]) - 3600) < 2
                   and abs((t0 - mac[12][2]) - 172810) < 2
                   and mac[11][3] == "kotlin daemon"))
    return checks


async def main():
    checks = readers()
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

            # 3b. el caso de Fision: el hijo (gradlew) termina y el nieto (el
            # daemon) se queda HUERFANO con la tuberia heredada. Desde pi ya
            # no se llega a el: solo lo mata el seguimiento durante la
            # herramienta
            await p.js("feed.innerHTML=''; nodes.clear()")
            await p.js("send({type:'prompt', message:'orphantool'})")
            await until(p, CHILD + " !== null")
            ids = await p.js("""(() => { const it = [...nodes.values()]
              .map(e => e.__item).filter(i => i && i.kind === 'tool'
                && i.args && i.args.gpid).pop();
              return it ? [it.args.pid, it.args.gpid] : null; })()""")
            kid, gkid = ids
            for _ in range(80):              # el hijo termina a los ~2 s
                if not alive(kid):
                    break
                await asyncio.sleep(0.1)
            orphan = (not alive(kid)) and alive(gkid)
            await asyncio.sleep(1.2)         # un par de fotos del seguimiento
            still_run = await p.js("state.running")
            await p.js("send({type:'abort', aggressive:true})")
            await asyncio.sleep(4.5)
            print("  huerfano:", kid, gkid, orphan, still_run,
                  alive(gkid), await p.js("state.running"),
                  await p.js(KILLED))
            checks += [
                ("se reproduce: el hijo termina y el nieto sigue, huerfano",
                 orphan and still_run is True),
                ("con el modo: mata al huerfano que retenia la tuberia",
                 not alive(gkid)),
                ("y el turno asienta",
                 (await p.js("state.running")) is False
                 and await p.js(KILLED)),
            ]
            reap(gkid)

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
