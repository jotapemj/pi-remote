"""Modelo por defecto: card en ajustes que lista los modelos y fija el default.

Backend: el puente persiste {provider, id} en el state y lo reaplica (set_model)
en cada pi nuevo, para que la eleccion sobreviva a reinicios y cambios de
proyecto. UI: fila «Modelo» bajo «Funciones» con el modelo actual en gris; al
abrir, lista los modelos con el actual marcado; al pulsar otro se selecciona sin
cerrar la vista.
"""
import asyncio
import tempfile
from pathlib import Path

from harness import Bridge, Page, report


def backend():
    import pi_web_bridge as B
    checks = []
    with tempfile.TemporaryDirectory() as td:
        old = B.STATE_FILE
        B.STATE_FILE = Path(td) / "state.json"
        try:
            checks.append(("sin default al principio",
                           B.read_default_model() is None))
            B.save_default_model("swift", "swift-27b")
            got = B.read_default_model()
            print("  default guardado: %r" % got)
            checks.append(("guarda y lee el modelo por defecto",
                           got == {"provider": "swift", "id": "swift-27b"}))
            # convive con lo demas del state (cwd/recientes)
            B.write_state("C:/x", ["C:/x"])
            checks.append(("el default sobrevive a otras escrituras del state",
                           B.read_default_model() == {"provider": "swift",
                                                       "id": "swift-27b"}))
            B.save_default_model("", "")
            checks.append(("provider/id vacios no cuentan como default",
                           B.read_default_model() is None))
        finally:
            B.STATE_FILE = old
    return checks


MODELS_JS = ("onRpc({command:'get_available_models', data:{models:["
             "{id:'qwen3-8b',name:'Qwen3 8B',provider:'local',contextWindow:32768},"
             "{id:'swift-27b',name:'swift-27b',provider:'swift',contextWindow:150000},"
             "{id:'ornith15',name:'ornith15',provider:'ornith',contextWindow:132000}"
             "]}})")


async def ui():
    checks = []
    with Bridge():
        async with Page(port=9377, collect_errors=True) as p:
            js = p.js
            await p.go()
            await js("try{if(ws)ws.onmessage=null;}catch(e){}")
            await js("setLang('es')")
            await js("state={running:false,waiting:false,alive:true,cwd:'C:/x',"
                     "sessionName:'s',model:'Qwen3 8B',modelId:'qwen3-8b',"
                     "modelProvider:'local',thinking:'x',context:null,"
                     "queue:{steering:[],followUp:[]},recent:[]}; CWD='C:/x'; paint()")
            await js("window.__sent=[]; ws.send=s=>window.__sent.push(JSON.parse(s))")

            # el menu de pi agent lleva la fila global con el modelo actual
            await js("menuSheet()")
            await asyncio.sleep(0.1)
            await js("(async()=>{[...document.querySelectorAll('#sheetBody .pick')]"
                     ".find(b => /pi agent/.test(b.textContent)).click();"
                     " await new Promise(r=>setTimeout(r,400));})()")
            row = await js("""(()=>{
              const b=[...document.querySelectorAll('#sheetBody .pick')];
              const mi=b.findIndex(x=>x.querySelector('.pval'));
              const m=b[mi];
              return m?[m.querySelector('.txt span').textContent,
                        !!m.querySelector('svg'),
                        m.querySelector('.pval').textContent]:null;})()""")
            print("  fila global: %r" % row)
            checks += [
                ("existe la fila «Ajustes globales» con icono",
                 bool(row) and row[0].startswith("Ajustes globales")
                 and row[1] is True),
                ("muestra el modelo actual en gris (val)",
                 bool(row) and "Qwen3 8B" in (row[2] or "")),
            ]

            # entrar a la pagina de modelo: pide la lista (mock la respuesta)
            await js("paintSheet('model')")
            asked = await js("!!window.__sent.find(x=>x.type==='get_available_models')")
            checks.append(("al abrir la pagina pide los modelos disponibles",
                           asked is True))
            await js(MODELS_JS)
            await asyncio.sleep(0.1)
            page = await js("""(()=>{
              const b=[...document.querySelectorAll('#sheetBody .mrow')];
              const rows=b.map(x=>({t:x.querySelector('.txt span').textContent,
                                     sel:x.classList.contains('sel'),
                                     chk:Number(getComputedStyle(
                                         x.querySelector('.chkslot')).opacity)}));
              return {title:$('#sheetTitle').textContent, n:rows.length, rows};})()""")
            print("  pagina modelo: %r" % page)
            sel = [r for r in page["rows"] if r["sel"]]
            unsel = [r for r in page["rows"] if not r["sel"]]
            checks += [
                ("la pagina lista los modelos disponibles", page["n"] == 3),
                ("el modelo actual sale marcado, y solo uno",
                 len(sel) == 1 and sel[0]["t"] == "Qwen3 8B"),
                ("el check del elegido se ve y el de los demas no (animable)",
                 sel and sel[0]["chk"] == 1
                 and all(r["chk"] == 0 for r in unsel)),
            ]

            # el texto del elegido va desplazado (deja sitio al check); los otros no
            shift = await js("""(()=>{
              const b=[...document.querySelectorAll('#sheetBody .mrow')];
              const s=b.find(x=>x.classList.contains('sel'));
              const u=b.find(x=>!x.classList.contains('sel'));
              const tx=e=>getComputedStyle(e.querySelector('.txt')).transform;
              const trans=getComputedStyle(s.querySelector('.txt')).transitionProperty;
              return [tx(s)!=='none', tx(u)==='none', trans.includes('transform')];})()""")
            print("  desplazamiento: %r" % shift)
            checks.append(("el texto del elegido se desplaza, con transicion",
                           shift == [True, True, True]))

            # elegir otro modelo: manda set_model, marca el nuevo, NO cierra
            await js("window.__sent=[]")
            await js("""(()=>{const b=[...document.querySelectorAll('#sheetBody .pick')];
              b.find(x=>x.querySelector('.txt span').textContent==='swift-27b').click();})()""")
            await asyncio.sleep(0.1)
            after = await js("""(()=>{
              const b=[...document.querySelectorAll('#sheetBody .mrow')];
              const sel=b.filter(x=>x.classList.contains('sel'))
                         .map(x=>x.querySelector('.txt span').textContent);
              const sm=window.__sent.find(x=>x.type==='set_model');
              return {open:$('#sheet').classList.contains('open'),
                      page:$('#sheetTitle').textContent, sel,
                      sent: sm?[sm.provider, sm.modelId]:null,
                      stateId: state.modelId};})()""")
            print("  tras elegir: %r" % after)
            checks += [
                ("pulsar manda set_model con provider y modelId",
                 after["sent"] == ["swift", "swift-27b"]),
                ("la marca pasa al nuevo modelo, y solo uno",
                 after["sel"] == ["swift-27b"]),
                ("la vista de modelo sigue abierta (sin dismiss)",
                 after["open"] is True and after["page"] == "Ajustes globales"),
                ("marca el nuevo modelo de forma optimista",
                 after["stateId"] == "swift-27b"),
            ]

            # volver a pi agent: el gris de la fila refleja el modelo nuevo
            await js("paintSheet('pagent')")
            await asyncio.sleep(0.05)
            back = await js("""(()=>{const b=[...document.querySelectorAll('#sheetBody .pick')];
              const m=b.find(x=>x.querySelector('.pval'));
              return m?m.querySelector('.pval').textContent:null;})()""")
            print("  fila tras elegir: %r" % back)
            checks.append(("la fila global muestra ya el modelo elegido",
                           back and "swift-27b" in back))
            checks.append(("sin errores de consola", not p.problems))
    return checks


async def e2e():
    """El default persistido se reaplica al abrir un proyecto (pi nuevo): el
    puente manda set_model y el estado sale en ese modelo, no en el de pi."""
    import json
    import websockets
    from harness import FakeProject, HERE, PORT, WS_URL
    checks = []
    sf = HERE / "_state_model.json"
    sf.write_text(json.dumps({"model": {"provider": "swift",
                                        "id": "swift-27b"}}), encoding="utf-8")
    try:
        with FakeProject("model") as proj, Bridge(state=sf, fresh=False):
            async with websockets.connect(WS_URL) as ws:
                await ws.recv()                       # snapshot inicial
                await ws.send(json.dumps({"type": "open_project",
                                          "path": proj.path}))
                model = None
                for _ in range(80):
                    m = json.loads(await asyncio.wait_for(ws.recv(), 15))
                    st = m.get("state") or {}
                    if st.get("model"):
                        model = st.get("model")
                        if model == "swift-27b":
                            break
                print("  modelo tras abrir proyecto: %r" % model)
                checks.append(("al abrir un pi nuevo se reaplica el default",
                               model == "swift-27b"))
    finally:
        sf.unlink(missing_ok=True)
    return checks


async def main():
    return backend() + await ui() + await e2e()


raise SystemExit(report(asyncio.run(main())))
