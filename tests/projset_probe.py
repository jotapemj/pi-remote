"""Ajustes por proyecto: los dos contenedores de la raiz, la pagina con
toggle en fase, cards de modelo/razonamiento, guardado con el check,
guarda al salir sin guardar, dialogos de confianza (picker y toggle) y la
procedencia Global/Proyecto en el readout. El picker muestra las zonas
prohibidas como filas grises deshabilitadas y desactiva el boton de subir
cuando el padre esta prohibido."""
import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from harness import Bridge, Page, FakeProject, WS_URL, report

TMP = Path(tempfile.gettempdir()) / "projset_probe_tmp"


class Area:
    def __enter__(self):
        shutil.rmtree(TMP, ignore_errors=True)
        TMP.mkdir(parents=True)
        return str(TMP)

    def __exit__(self, *a):
        shutil.rmtree(TMP, ignore_errors=True)


def backend():
    import pi_web_bridge as B
    checks = []
    with Area() as td:
        root = Path(td) / "proj"
        (root / ".pi").mkdir(parents=True)
        B.AGENT_DIR = Path(td)
        try:
            # needs_trust: espejo del check de pi
            empty = Path(td) / "empty"
            empty.mkdir()
            checks.append(("carpeta sin .pi no pide confianza",
                           B.needs_trust(str(empty)) is False))
            (root / ".pi" / "settings.json").write_text(
                "{}", encoding="utf-8")
            checks.append((".pi/settings.json pide confianza",
                           B.needs_trust(str(root)) is True))
            ext = Path(td) / "ext" / ".pi" / "extensions"
            ext.mkdir(parents=True)
            checks.append((".pi/extensions pide confianza",
                           B.needs_trust(str(ext.parent.parent)) is True))

            # list_dirs: los bloqueados salen con flag, sin marca
            users = Path.home().parent
            if os_name_nt() and (users / "AppData").is_dir():
                dirs = {d["name"]: d for d in B.list_dirs(users)}
                ad = dirs.get("AppData")
                checks += [
                    ("AppData sale en la lista del picker", ad is not None),
                    ("AppData lleva el flag de bloqueado",
                     bool(ad and ad["blocked"] is True)),
                    ("el bloqueado no lleva marca de proyecto",
                     bool(ad) and ad["mark"] is None),
                ]

            # upBlocked: el temp vive dentro de AppData (bloqueada)
            tdir = Path(tempfile.gettempdir())
            checks.append(("el padre del temp esta prohibido",
                           B.is_blocked(tdir.parent)))

            # delete_project_settings: el toggle off borra el fichero
            err = B.save_project_settings(str(root), {"defaultModel": "x"})
            p = root / ".pi" / "settings.json"
            checks.append(("save escribe el fichero",
                           err is None and p.exists()))
            err = B.delete_project_settings(str(root))
            checks += [
                ("delete sin error", err is None),
                ("delete borra el fichero", not p.exists()),
            ]
            checks.append(("delete en carpeta inexistente da error",
                           "not a directory" in B.delete_project_settings(
                               str(root / "no"))))
        finally:
            del B.AGENT_DIR
    return checks


def os_name_nt():
    import os
    return os.name == "nt"


async def ui():
    checks = []
    with Area() as td:
        proj = Path(td) / "proj"
        (proj / ".pi").mkdir(parents=True)
        (proj / ".pi" / "settings.json").write_text(
            json.dumps({"defaultModel": "swift/swift-27b"}), encoding="utf-8")
        with Bridge(extra={"PI_AGENT_DIR": td}):
            async with Page(port=9386) as p:
                js = p.js
                await p.go()
                await js("setLang('en')")
                # captura en passthrough: lo que se envia llega al puente
                # (bind: sin el this del socket, send lanza Illegal invocation)
                await js("window.__sent=[]; window.__realSend=ws.send.bind(ws);"
                         " ws.send=s=>{window.__sent.push(JSON.parse(s));"
                         " return window.__realSend(s);}")
                projjs = json.dumps(str(proj))

                # ---- navegacion: los dos contenedores en la raiz ----
                await js("paintSheet('root')")
                rootrows = await js("""[...document.querySelectorAll('#sheetBody .pick')]
                  .map(b=>b.querySelector('.txt span').textContent)""")
                checks += [
                    ("la raiz lista 'pi remote settings'",
                     "pi remote settings" in rootrows),
                    ("la raiz lista 'pi agent settings'",
                     "pi agent settings" in rootrows),
                ]
                await js("(async()=>{[...document.querySelectorAll('#sheetBody .pick')]"
                         ".find(b=>/pi remote/.test(b.textContent)).click();"
                         " await new Promise(r=>setTimeout(r,400));})()")
                premote = await js("""[...document.querySelectorAll('#sheetBody .pick')]
                  .map(b=>b.querySelector('.txt span').textContent)""")
                checks += [
                    ("pi remote settings lista Functions",
                     "Functions" in premote),
                    ("pi remote settings lista Trusted paths",
                     "Trusted paths" in premote),
                ]
                await js("goBack()")
                await asyncio.sleep(0.4)
                await js("(async()=>{[...document.querySelectorAll('#sheetBody .pick')]"
                         ".find(b=>/pi agent/.test(b.textContent)).click();"
                         " await new Promise(r=>setTimeout(r,400));})()")
                pagent = await js("""[...document.querySelectorAll('#sheetBody .pick')]
                  .map(b=>b.querySelector('.txt span').textContent)""")
                checks += [
                    ("pi agent settings lista Global settings",
                     "Global settings" in pagent),
                    ("pi agent settings lista Project settings",
                     "Project settings" in pagent),
                ]

                # ---- pagina de ajustes por proyecto: toggle off ----
                await js("state={running:false,waiting:false,alive:true,"
                         "cwd:%s,sessionName:'s',model:'Qwen3 8B',"
                         "modelId:'qwen3-8b',modelProvider:'local',"
                         "thinking:'medium',context:null,"
                         "queue:{steering:[],followUp:[]},recent:[],"
                         "projSettings:{},projTrusted:true}; CWD=%s; paint()"
                         % (projjs, projjs))
                await js("goPage('projset')")
                await asyncio.sleep(0.4)
                off = await js("""(()=>{
                  const rows=[...document.querySelectorAll('#sheetBody .pick.off')];
                  const sw=document.querySelector('#sheetBody .sw');
                  return {n:rows.length, dis:rows.every(r=>r.disabled),
                          sw:sw?sw.getAttribute('aria-checked'):null,
                          ok:$('#sheetOk').hidden};})()""")
                checks += [
                    ("toggle off: las dos cards estan deshabilitadas",
                     off["n"] == 2 and off["dis"] is True),
                    ("toggle off: el switch esta apagado", off["sw"] == "false"),
                    ("toggle off: sin check de guardar", off["ok"] is True),
                ]

                # ---- toggle on: plantilla global, cards vivas, check ----
                await js("document.querySelector('#sheetBody .sw').click()")
                await asyncio.sleep(0.15)
                on = await js("""(()=>{
                  const rows=[...document.querySelectorAll('#sheetBody .pick')];
                  return {n:rows.length, off:rows.filter(r=>r.classList.contains('off')).length,
                          m:rows.find(r=>/Model/.test(r.textContent))
                            ?rows.find(r=>/Model/.test(r.textContent)).querySelector('.pval').textContent:null,
                          t:rows.find(r=>/Reasoning/.test(r.textContent))
                            ?rows.find(r=>/Reasoning/.test(r.textContent)).querySelector('.pval').textContent:null,
                          ok:$('#sheetOk').hidden};})()""")
                checks += [
                    ("toggle on: las cards se activan", on["n"] == 2 and on["off"] == 0),
                    ("la card de modelo arranca con el global",
                     bool(on["m"]) and "qwen3-8b" in on["m"]),
                    ("la card de razonamiento arranca con el global",
                     bool(on["t"]) and "medium" in on["t"]),
                    ("con cambios sin guardar aparece el check", on["ok"] is False),
                ]

                # ---- subvista modelo: ir y volver NO debe preguntar guardar
                # (staged sucio; el guard solo salta al salir de projset) ----
                await js("goPage('projmodel')")
                await asyncio.sleep(0.4)
                await js("$('#sheetBack').click()")
                await asyncio.sleep(0.4)
                sub = await js("[$('#modal').classList.contains('open'), sheetPage]")
                checks.append(("volver de modelo no pregunta guardar",
                               sub[0] is False and sub[1] == "projset"))

                # ---- guardar: check -> dialogo -> payload completo ----
                await js("$('#sheetOk').click()")
                await asyncio.sleep(0.15)
                dlg = await js("""(()=>[document.querySelector('#modalTitle').textContent,
                  document.querySelector('#modalOk').textContent])()""")
                checks.append(("el guardado pide confirmacion",
                               dlg and dlg[0] == "Save project settings?"))
                await js("$('#modalOk').click()")
                await asyncio.sleep(0.2)
                save = await js("window.__sent.find(x=>x.type==='project_settings_save')")
                checks += [
                    ("el payload lleva el modelo del proyecto",
                     bool(save) and save["settings"]["defaultModel"] == "qwen3-8b"
                     and save["settings"]["defaultProvider"] == "local"),
                    ("el payload lleva el nivel de razonamiento",
                     bool(save) and save["settings"]["defaultThinkingLevel"] == "medium"),
                    ("guardado limpio: el check desaparece",
                     (await js("$('#sheetOk').hidden")) is True),
                ]

                # ---- back con cambios sin guardar: preguntar ----
                await js("document.querySelector('#sheetBody .sw').click()")
                await asyncio.sleep(0.15)          # toggle off = cambio en fase
                await js("window.__sent=[]")
                await js("$('#sheetBack').click()")
                await asyncio.sleep(0.2)
                uns = await js("""(()=>[document.querySelector('#modalTitle').textContent,
                  document.querySelector('#modalNo').textContent,
                  document.querySelector('#modalOk').textContent])()""")
                checks.append(("salir sin guardar pregunta",
                               uns and uns[0] == "Save changes?"
                               and uns[1] == "no" and uns[2] == "yes"))
                await js("$('#modalNo').click()")  # no: descartar y salir
                await asyncio.sleep(0.4)
                checks += [
                    ("no guardar: no se envio nada",
                     (await js("window.__sent.length")) == 0),
                    ("no guardar: la hoja volvio a pi agent",
                     (await js("$('#sheetTitle').textContent")) == "pi agent settings"),
                ]

                # ---- back con cambios: si = guardar y salir ----
                # primer guardado de verdad (el override queda en el puente)
                await js("goPage('projset')")
                await asyncio.sleep(0.4)
                await js("document.querySelector('#sheetBody .sw').click()")
                await asyncio.sleep(0.15)
                await js("window.__sent=[]")
                await js("$('#sheetOk').click()")
                await asyncio.sleep(0.15)
                await js("$('#modalOk').click()")
                await asyncio.sleep(0.3)
                s1 = await js("window.__sent.find(x=>x.type==='project_settings_save')")
                checks.append(("el override se guardo sin borrado",
                               bool(s1) and not s1.get("delete")
                               and s1["settings"]["defaultModel"] == "qwen3-8b"))
                # y el borrado por el guard: off = dirty contra el override
                await js("document.querySelector('#sheetBody .sw').click()")
                await asyncio.sleep(0.15)
                await js("window.__sent=[]")
                await js("$('#sheetBack').click()")
                await asyncio.sleep(0.2)
                await js("$('#modalOk').click()")  # si: guardar y salir
                await asyncio.sleep(0.45)
                s2 = await js("window.__sent.find(x=>x.type==='project_settings_save')")
                checks += [
                    ("si guardar: se envio el borrado (toggle off)",
                     bool(s2) and s2.get("delete") is True),
                    ("si guardar: la hoja salio",
                     (await js("$('#sheetTitle').textContent")) == "pi agent settings"),
                ]

                # ---- procedencia en el readout ----
                await js("state.projSettings={defaultModel:'swift/swift-27b'};"
                         " state.projTrusted=true; paint()")
                prov1 = await js("document.querySelector('#cmeta').textContent")
                await js("state.projSettings={}; paint()")
                prov2 = await js("document.querySelector('#cmeta').textContent")
                checks += [
                    ("con override confiado: prefijo Project",
                     bool(prov1) and prov1.startswith("Project:")),
                    ("sin override: prefijo Global",
                     bool(prov2) and prov2.startswith("Global:")),
                ]

                # ---- dialog de confianza en el toggle (proyecto sin trust) ----
                # carpeta fresca sin confiar (el save de arriba dejo proj confiado)
                projU = Path(td) / "projU"
                (projU / ".pi").mkdir(parents=True)
                (projU / ".pi" / "settings.json").write_text("{}", encoding="utf-8")
                await js("state.projTrusted=false; state.projSettings={};"
                         " projSavedKey=null; state.cwd=%s; paint()"
                         % json.dumps(str(projU)))
                await js("goPage('projset')")
                await asyncio.sleep(0.4)
                await js("document.querySelector('#sheetBody .sw').click()")
                await asyncio.sleep(0.3)
                tw = await js("""(()=>[document.querySelector('#modalTitle').textContent,
                  document.querySelector('#modalBody').innerHTML,
                  document.querySelector('#modalOk').textContent,
                  document.querySelector('#modalNo').textContent])()""")
                checks += [
                    ("toggle sin confianza abre el dialogo",
                     bool(tw) and tw[0] == "Project trust"),
                    ("el texto lleva la carpeta en cursiva",
                     bool(tw) and "<em>" in tw[1] and str(projU) in tw[1].replace("\\\\", "\\")),
                    ("los botones son Trust / Don't trust",
                     bool(tw) and tw[2] == "Trust" and tw[3] == "Don't trust"),
                ]
                await js("window.__sent=[]")
                await js("$('#modalOk').click()")
                await asyncio.sleep(0.2)
                ts = await js("window.__sent.find(x=>x.type==='trust_set')")
                checks += [
                    ("Trust manda trust_set(true)",
                     bool(ts) and ts["decision"] is True),
                    ("tras confiar, las cards se activan",
                     (await js("[...document.querySelectorAll('#sheetBody .pick.off')].length")) == 0),
                ]

                # ---- dialog de confianza del picker: trustAsk directo ----
                # carpeta sin recursos de pi: no hay dialogo
                plain = Path(td) / "plain"
                plain.mkdir()
                r1 = await js("(async()=>trustAsk(%s))()" % json.dumps(str(plain)))
                checks.append(("sin recursos .pi: sin dialogo y adelante (true)",
                               r1 is True
                               and (await js("$('#modal').classList.contains('open')")) is False))
                # carpeta con .pi/settings.json y sin confiar: dialogo. proj ya
                # quedo confiado en el test anterior, asi que toca otra
                proj2 = Path(td) / "proj2"
                (proj2 / ".pi").mkdir(parents=True)
                (proj2 / ".pi" / "settings.json").write_text(
                    "{}", encoding="utf-8")
                # sin devolver la promesa: awaitPromise se quedaria a esperarla
                await js("(()=>{window.__ta = trustAsk(%s);})()" % json.dumps(str(proj2)))
                await asyncio.sleep(0.3)
                open2 = await js("$('#modal').classList.contains('open')")
                checks.append(("con recursos .pi el picker pregunta",
                               open2 is True))
                await js("$('#modalOk').click()")
                r2 = await js("window.__ta")
                checks.append(("Trust en el picker confia", r2 is True))

                # ---- toggle en carpeta sin .pi y sin trust: se activa sin
                # dialogo (el bug de JP: el toggle no hacia nada) ----
                plain2 = Path(td) / "plainproj"
                plain2.mkdir()
                await js("state.projTrusted=false; state.projSettings={};"
                         " projSavedKey=null; state.cwd=%s; paint()"
                         % json.dumps(str(plain2)))
                await js("goPage('projset')")
                await asyncio.sleep(0.4)
                await js("window.__sent=[]")
                await js("document.querySelector('#sheetBody .sw').click()")
                await asyncio.sleep(0.3)
                pon = await js("""(()=>({
                  modal:$('#modal').classList.contains('open'),
                  sw:document.querySelector('#sheetBody .sw').getAttribute('aria-checked'),
                  off:[...document.querySelectorAll('#sheetBody .pick.off')].length}))()""")
                checks.append(("carpeta sin .pi: el toggle se activa sin dialogo",
                               pon["modal"] is False and pon["sw"] == "true"
                               and pon["off"] == 0))

                # ---- picker: filas bloqueadas y boton de subir ----
                await js("browse('')")   # raiz: la carpeta Users
                await asyncio.sleep(0.5)
                uproot = await js("document.querySelector('#sheetBody .iconbtn').disabled")
                checks.append(("subir a la raiz de unidad queda deshabilitado",
                               uproot is True))
                # dentro del home: AppData sale grises y el padre (Users) esta
                # permitido
                await js("browse(%s)" % json.dumps(str(Path.home())))
                await asyncio.sleep(0.5)
                picker = await js("""(()=>{
                  const rows=[...document.querySelectorAll('#sheetBody .pick')];
                  const ad=rows.find(r=>/AppData/.test(r.textContent));
                  return {ad: ad?[ad.classList.contains('off'), ad.disabled]:null,
                          up: document.querySelector('#sheetBody .iconbtn').disabled};})()""")
                checks += [
                    ("el picker muestra AppData deshabilitado",
                     bool(picker["ad"]) and picker["ad"][0] is True
                     and picker["ad"][1] is True),
                    ("subir desde el home esta activo", picker["up"] is False),
                ]
                # dentro del temp: el padre (AppData) esta prohibido
                await js("browse(%s)" % json.dumps(str(Path(tempfile.gettempdir()))))
                await asyncio.sleep(0.5)
                updis = await js("document.querySelector('#sheetBody .iconbtn').disabled")
                checks.append(("subir fuera del temp queda deshabilitado",
                               updis is True))
                checks.append(("sin errores de consola", not p.problems))
    return checks


async def e2e():
    """Abrir un proyecto confiado con settings: el estado lleva las claves."""
    import websockets
    with Area() as td:
        proj = Path(td) / "proj"
        (proj / ".pi").mkdir(parents=True)
        (proj / ".pi" / "settings.json").write_text(
            json.dumps({"defaultModel": "swift/swift-27b",
                        "defaultThinkingLevel": "low"}), encoding="utf-8")
        (Path(td) / "trust.json").write_text(
            json.dumps({str(proj.resolve()): True}), encoding="utf-8")
        with Bridge(extra={"PI_AGENT_DIR": td}):
            async with websockets.connect(WS_URL) as ws:
                await ws.recv()
                await ws.send(json.dumps({"type": "open_project",
                                          "path": str(proj)}))
                st = None
                for _ in range(80):
                    m = json.loads(await asyncio.wait_for(ws.recv(), 15))
                    if m.get("type") == "state":
                        st = m["state"]
                        if st.get("cwd") == str(proj):
                            break
                ps = (st or {}).get("projSettings") or {}
                checks = [
                    ("el estado lleva projTrusted",
                     bool(st) and st.get("projTrusted") is True),
                    ("el estado lleva los settings del proyecto",
                     ps.get("defaultModel") == "swift/swift-27b"
                     and ps.get("defaultThinkingLevel") == "low"),
                ]
                print("  estado: %r" % (st and st.get("projSettings")))
                return checks
    return []


async def main():
    return backend() + await ui() + await e2e()


raise SystemExit(report(asyncio.run(main())))
