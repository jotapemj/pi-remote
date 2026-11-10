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


def hex_rgb(h):
    h = h.lstrip("#")
    return "rgb(%d, %d, %d)" % tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


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
                line = None
                for _ in range(40):
                    line = await js("""(() => { const b = $('#bgStrip .bgline');
                      return b && !$('#bgStrip').hidden ? {t: b.textContent,
                        h: b.getBoundingClientRect().height,
                        c: getComputedStyle(b).color,
                        mint: getComputedStyle(document.documentElement)
                          .getPropertyValue('--mint').trim(),
                        n: document.querySelectorAll('#bgStrip .bgline').length}
                      : null; })()""")
                    if line:
                        break
                    await asyncio.sleep(0.25)
                print("  linea:", line)
                checks += [
                    ("una sola linea al fondo, no una pastilla por tarea",
                     bool(line) and line["n"] == 1 and 0 < line["h"] < 40),
                    ("solo texto, como Claude: cuantas hay en marcha",
                     bool(line) and line["t"] == "1 tarea en ejecución"),
                    ("en el menta de los enlaces, sin un cuarto acento",
                     bool(line) and line["mint"] != ""
                     and line["c"] == hex_rgb(line["mint"])),
                ]

                ROWS = """[...document.querySelectorAll('#sheetBody .bgrow')]
                  .map(r => ({cls: r.className.split(' ').pop(),
                              t: r.textContent,
                              stop: !!r.querySelector('.bgstop svg')}))"""
                await js("$('#bgStrip .bgline').click()")
                rows = []
                for _ in range(30):
                    rows = await js(ROWS)
                    if rows:
                        break
                    await asyncio.sleep(0.2)
                heads = await js("[...document.querySelectorAll('#sheetBody"
                                 " .bghead')].map(h => h.textContent)")
                for r in rows:
                    print("   ", r)
                print("  secciones:", heads)
                checks += [
                    ("la linea abre la hoja con En ejecucion y Finalizadas",
                     heads == ["En ejecución", "Finalizadas 3"]),
                    ("todo el historial del proyecto, la ultima en acabar arriba",
                     [r["t"][:2] for r in rows] == ["#1", "#2", "#3", "#5"]),
                    ("cada fila con su estado (el .code manda sobre el json)",
                     [r["cls"] for r in rows]
                     == ["running", "done", "failed", "done"]),
                    ("la que corre lleva su boton de parar; las demas no",
                     [r["stop"] for r in rows] == [True, False, False, False]),
                    ("la fallida dice su codigo",
                     len(rows) == 4 and "falló (código 2)" in rows[2]["t"]),
                ]
                if os.environ.get("PI_SHOT"):
                    await asyncio.sleep(0.6)
                    await p.shot(os.environ["PI_SHOT"])

                await js("[...document.querySelectorAll('#sheetBody .bghead')]"
                         ".pop().click()")
                await asyncio.sleep(0.3)
                folded = await js(ROWS)
                checks.append(("Finalizadas se pliega", len(folded) == 1))
                await js("[...document.querySelectorAll('#sheetBody .bghead')]"
                         ".pop().click()")
                await asyncio.sleep(0.3)

                # la viva: su log limpio; atras vuelve a la lista
                await js("$('#sheetBody .bgrow.running').click()")
                log = None
                for _ in range(30):
                    log = await js("(() => { const l = $('.bglog');"
                                   " return l ? l.textContent : null; })()")
                    if log:
                        break
                    await asyncio.sleep(0.2)
                await js("$('#sheetBack').click()")
                await asyncio.sleep(0.5)
                back = await js(ROWS)
                checks += [
                    ("tocar la fila abre su log limpio",
                     log == "100%\nok: modulo a"),
                    ("y atras vuelve a la lista", len(back) == 4),
                ]

                # la fila del chat de un bg_run sigue a su tarea (la #1 vive)
                await js("$('#sheet').classList.remove('open');"
                         " send({type:'prompt', message:'bgrunrow'})")
                ROW = """(() => { const b = document.querySelector(
                  '#feed .bgtool'); if(!b) return null;
                  return {t: b.textContent, bg: b.dataset.bg,
                    cls: b.className, shine: !!b.querySelector('.shine'),
                    grouped: !!b.closest('.toolgroup'),
                    groups: document.querySelectorAll('#feed .toolgroup').length,
                    h: b.getBoundingClientRect().height}; })()"""
                row = None
                for _ in range(40):
                    row = await js(ROW)
                    if row and await js("state.running === false"):
                        break
                    await asyncio.sleep(0.25)
                print("  fila:", row)
                checks += [
                    ("la fila de bg_run lleva su tarea y se pinta",
                     bool(row) and row["bg"] == "1" and row["h"] > 0),
                    ("mientras corre: Ejecutando, con brillo",
                     bool(row) and row["t"].startswith("Ejecutando")
                     and row["shine"] and "#1 tarea 1" in row["t"]),
                    ("vive sola: no entra en el tramo plegado de los read",
                     bool(row) and not row["grouped"] and row["groups"] >= 2),
                ]
                await js("$('#feed .bgtool').click()")
                await asyncio.sleep(0.6)
                opened = await js("[sheetPage, bgId, $('#sheet').classList"
                                  ".contains('open')]")
                checks.append(("tocarla abre la salida de su tarea",
                               opened == ["bgtask", 1, True]))
                await js("openBgList()")
                for _ in range(30):
                    if await js(ROWS):
                        break
                    await asyncio.sleep(0.2)

                # parar desde la fila
                await js("$('#sheetBody .bgstop').click()")
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
                after = await js(ROWS)
                gone = await js("$('#bgStrip').hidden")
                checks += [
                    ("parar mata el proceso de verdad", dead),
                    ("y la apunta como parada, sin despertar al agente",
                     j1["status"] == "killed" and j1.get("notified") is True),
                    ("la hoja la pasa a Finalizadas",
                     not any(r["cls"] == "running" for r in after)
                     and any(r["t"].startswith("#1") and "parada" in r["t"]
                             for r in after)),
                    ("sin nada en marcha, la linea desaparece", gone is True),
                ]
                row2 = await js(ROW)
                checks.append(("la fila del chat pasa a parada, con lo que duro",
                               bool(row2) and row2["t"].startswith("parada")
                               and not row2["shine"]))
                await js("$('#sheet').classList.remove('open')")

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
