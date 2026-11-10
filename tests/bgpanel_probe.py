"""Panel de tareas en segundo plano, del lado del puente y de la pagina.

La extension deja las tareas en una carpeta; aqui se fabrican a mano (con
un proceso vivo de verdad para la que corre) en una carpeta temporal:
- la tira muestra las de ESTE proyecto, vivas o recientes, con su estado y
  la ultima linea de salida limpia (sin \\r de barra ni colores);
- tocar una abre su hoja con el log y Parar; parar mata el proceso y la
  apunta como parada sin despertar al agente;
- una de otro proyecto no se ve ni se lee;
- el aviso de la extension (mensaje custom) sale como nota traducida;
- encender el interruptor ofrece aplicar las reglas de bash
  (shellTools.bg_run en la config de permission-system) y lo escribe;
- el aborto agresivo no toca las tareas ni lo que cuelga de ellas.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time

from harness import ROOT, Bridge, FakeProject, Page, report

sys.path.insert(0, str(ROOT))
import pi_web_bridge as B          # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def job(d, jid, cwd, status, pid=0, code=None, ended=None, label=None,
        log="", codefile=None):
    now = time.time() * 1000
    j = {"id": jid, "label": label or "tarea %d" % jid,
         "command": "make %d" % jid, "cwd": cwd, "pid": pid,
         "started": now - 65000, "status": status, "code": code,
         "ended": ended}
    with open(os.path.join(d, "%d.json" % jid), "w", encoding="utf-8") as f:
        json.dump(j, f)
    with open(os.path.join(d, "%d.log" % jid), "w", encoding="utf-8",
              newline="") as f:
        f.write(log)
    if codefile is not None:
        with open(os.path.join(d, "%d.code" % jid), "w") as f:
            f.write(codefile)


def unit():
    rows = [(10, 1, 0, "bash"), (11, 10, 0, "make"), (12, 11, 0, "gcc"),
            (20, 1, 0, "otro")]
    keep = B.bg_protected(rows, pids={10})
    return [("el aborto agresivo respeta la tarea y todo lo que cuelga",
             keep == {10, 11, 12})]


async def in_page():
    checks = []
    tmp = tempfile.mkdtemp(prefix="pi-bgpanel-")
    jobs = os.path.join(tmp, "jobs")
    os.makedirs(jobs)
    cfg = os.path.join(tmp, "perm.json")
    with open(cfg, "w") as f:
        json.dump({"permission": {"*": "allow"}}, f)
    sleeper = subprocess.Popen([sys.executable, "-c",
                                "import time; time.sleep(120)"])
    try:
        with FakeProject() as proj, Bridge(extra={
                "PI_REMOTE_JOBS": jobs, "PI_REMOTE_PERMCFG": cfg}):
            now = time.time() * 1000
            job(jobs, 1, proj.path, "running", pid=sleeper.pid,
                log="compilando\r 50%\r100%\n\x1b[32mok\x1b[0m: modulo a\n")
            job(jobs, 2, proj.path, "running", pid=999999, codefile="0")
            job(jobs, 3, proj.path, "failed", code=2, ended=now - 1000)
            job(jobs, 4, os.path.join(tmp, "otro"), "running",
                pid=sleeper.pid, log="ajena\n")
            job(jobs, 5, proj.path, "done", code=0, ended=now - 3600e3)
            async with Page() as p:
                js = p.js
                await p.go()
                await asyncio.sleep(0.8)
                await js("setLang('es'); send({type:'open_project', path:%s})"
                         % json.dumps(proj.path))
                chips = []
                for _ in range(40):
                    chips = await js("""[...document.querySelectorAll(
                      '#bgStrip .bgchip')].map(c => ({cls: c.className,
                      t: c.textContent, w: c.getBoundingClientRect().width}))""")
                    if len(chips) == 3:
                        break
                    await asyncio.sleep(0.25)
                for c in chips:
                    print("   ", c)
                cl = [c["cls"].split()[-1] for c in chips]
                checks += [
                    ("la tira muestra las de este proyecto, vivas o recientes",
                     len(chips) == 3 and all(c["w"] > 0 for c in chips)),
                    ("cada una con su estado (el .code manda sobre el json)",
                     cl == ["running", "done", "failed"]),
                    ("la viva da su tiempo y la ultima linea, limpia",
                     bool(chips) and "en marcha" in chips[0]["t"]
                     and chips[0]["t"].endswith("ok: modulo a")),
                    ("la fallida dice su codigo",
                     len(chips) == 3 and "falló (código 2)" in chips[2]["t"]),
                ]

                await js("$('#bgStrip .bgchip').click()")
                log = None
                for _ in range(30):
                    log = await js("(() => { const l = $('.bglog');"
                                   " return l ? [l.textContent,"
                                   " !!$('.fbar button')] : null; })()")
                    if log:
                        break
                    await asyncio.sleep(0.2)
                print("  hoja:", log)
                checks.append(("tocarla abre su log limpio y el boton Parar",
                               bool(log) and log[0] == "100%\nok: modulo a"
                               and log[1]))
                if os.environ.get("PI_SHOT"):
                    await asyncio.sleep(0.6)
                    await p.shot(os.environ["PI_SHOT"])
                await js("$('.fbar button').click()")
                await asyncio.sleep(0.3)
                await js("$('#modalOk').click()")
                dead = False
                for _ in range(40):
                    if not B.pid_alive(sleeper.pid):
                        dead = True
                        break
                    await asyncio.sleep(0.25)
                with open(os.path.join(jobs, "1.json"), encoding="utf-8") as f:
                    j1 = json.load(f)
                await asyncio.sleep(2.5)
                first = await js("$('#bgStrip .bgchip').textContent")
                checks += [
                    ("parar mata el proceso de verdad", dead),
                    ("y la apunta como parada, sin despertar al agente",
                     j1["status"] == "killed" and j1.get("notified") is True),
                    ("la tira lo refleja", "parada" in (first or "")),
                ]

                ajena = await js("""new Promise(r => {
                  const om = ws.onmessage;
                  ws.onmessage = e => { const m = JSON.parse(e.data);
                    if(m.type === 'rpc' && m.command === 'bg_log'
                       && m.data.id === 4){ ws.onmessage = om; r(m.data); }
                    else om.call(ws, e); };
                  send({type:'bg_log', id:4}); })""")
                checks.append(("una de otro proyecto no se lee",
                               "error" in ajena and "lines" not in ajena))

                # aviso de la extension: nota traducida
                await js("send({type:'prompt', message:'bgnotify'})")
                nota = None
                for _ in range(30):
                    nota = await js("""(() => { const n = [...document
                      .querySelectorAll('.note')].map(e => e.textContent)
                      .find(t => t.includes('#7')); return n || null; })()""")
                    if nota:
                        break
                    await asyncio.sleep(0.2)
                print("  nota:", nota)
                checks.append(("el aviso de la extension sale como nota traducida",
                               bool(nota) and "tarea #7 build" in nota
                               and "falló (código 2)" in nota))

                # interruptor: ofrece aplicar las reglas de bash y lo escribe
                await js("closeModal && closeModal();"
                         " sheetStack=[]; paintSheet('functions');"
                         " $('#sheet').classList.add('open')")
                await asyncio.sleep(0.4)
                await js("$('#bgTasksSw').click()")
                dlg = None
                for _ in range(30):
                    dlg = await js("$('#modal').classList.contains('open')"
                                   " ? [$('#modalTitle').textContent,"
                                   " !!$('#bgPermCb'), $('#bgPermCb') &&"
                                   " $('#bgPermCb').checked] : null")
                    if dlg:
                        break
                    await asyncio.sleep(0.2)
                print("  dialogo:", dlg)
                checks.append(("encender ofrece aplicar las reglas de bash, marcado",
                               dlg == ["Tareas en segundo plano", True, True]))
                await js("$('#modalOk').click()")
                await asyncio.sleep(1.0)
                with open(cfg, encoding="utf-8") as f:
                    c = json.load(f)
                st = await js("[state.bgTasks, $('#bgTasksSw').getAttribute("
                              "'aria-checked')]")
                checks += [
                    ("acepta: bg_run queda en shellTools, sin tocar el resto",
                     c.get("shellTools", {}).get("bg_run")
                     == {"commandArgument": "command"}
                     and c.get("permission") == {"*": "allow"}),
                    ("y el interruptor queda encendido", st == [True, "true"]),
                ]
                problems = [x for x in p.problems if "favicon" not in x[1]]
                checks.append(("sin fallos en consola", not problems))
                if problems:
                    print(problems[:4])
    finally:
        if sleeper.poll() is None:
            sleeper.kill()
    return checks


async def main():
    return unit() + await in_page()


raise SystemExit(report(asyncio.run(main())))
