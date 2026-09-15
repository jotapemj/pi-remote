"""Editar modelo: lapiz en la card que abre la hoja de parametros (contextWindow
y maxTokens editables, id y modalidades de solo lectura). El check de confirmar
aparece al haber cambios validos; el dialogo avisa de que se escribe models.json
y de que se aplica al reiniciar. El puente hace el round-trip del fichero."""
import asyncio
import json
import tempfile
from pathlib import Path

from harness import Bridge, Page, report


def backend():
    import pi_web_bridge as B
    checks = []
    with tempfile.TemporaryDirectory() as td:
        models = Path(td) / "models.json"
        models.write_text(json.dumps({"providers": {
            "local": {"baseUrl": "http://x/v1", "apiKey": "k", "models": [
                {"id": "a", "contextWindow": 100, "maxTokens": 10}]},
            "swift": {"baseUrl": "http://y/v1", "models": [
                {"id": "b", "contextWindow": 200, "maxTokens": 20}]},
        }}), encoding="utf-8")
        B.AGENT_DIR = Path(td)          # PI_MODELS_JSON no set: cae aqui
        try:
            err = B.save_model_params("swift", "b", 4096, 512)
            d = json.loads(models.read_text(encoding="utf-8"))
            m = d["providers"]["swift"]["models"][0]
            print("  escrito: %r" % m)
            checks += [
                ("escribe sin error", err is None),
                ("actualiza contextWindow y maxTokens",
                 m["contextWindow"] == 4096 and m["maxTokens"] == 512),
                ("round-trip: el resto del fichero intacto",
                 d["providers"]["local"]["models"][0]["contextWindow"] == 100
                 and d["providers"]["swift"]["baseUrl"] == "http://y/v1"),
            ]
            checks.append(("modelo inexistente da error",
                           "not found" in B.save_model_params("swift", "z", 1, 1)))
        finally:
            del B.AGENT_DIR
    return checks


async def ui():
    checks = []
    with tempfile.TemporaryDirectory() as td:
        models = Path(td) / "models.json"
        models.write_text(json.dumps({"providers": {
            "local": {"baseUrl": "http://x/v1", "apiKey": "k", "models": [
                {"id": "qwen3-8b", "name": "Qwen3 8B", "contextWindow": 32768,
                 "maxTokens": 4096, "input": ["text"]}]}},
        }), encoding="utf-8")
        with Bridge(extra={"PI_MODELS_JSON": str(models)}):
            async with Page(port=9351) as p:
                js = p.js
                await p.go()
                # guardar el handler real: la confirmacion depende del rpc
                # que el puente manda por websocket de verdad
                await js("window.__om = ws.onmessage; ws.onmessage = null;")
                await js("setLang('es')")

                # abrir la pagina de modelos; la lista se inyecta (fake_pi
                # trae su propia) y coincide con lo que hay en models.json
                await js("menuSheet()")
                await asyncio.sleep(0.1)
                await js("paintSheet('model')")
                await js("onRpc({command:'get_available_models', data:{models:["
                         "{id:'qwen3-8b',name:'Qwen3 8B',provider:'local',"
                         "contextWindow:32768,maxTokens:4096,input:['text']}]}})")
                await asyncio.sleep(0.2)

                # cada fila lleva su lapiz
                pens = await js("""(()=>{
                  const b=[...document.querySelectorAll('#sheetBody .mrow')];
                  return {n:b.length,
                          pen:b.map(x=>!!x.querySelector('.pen svg')),
                          title:$('#sheetTitle').textContent};})()""")
                print("  filas: %r" % pens)
                checks += [
                    ("la pagina lista el modelo", pens["n"] == 1),
                    ("cada fila lleva el lapiz", all(pens["pen"])),
                ]

                # pulsar el lapiz abre modelEdit con los valores cargados
                await js("document.querySelector('#sheetBody .mrow .pen').click()")
                await asyncio.sleep(0.4)
                ed = await js("""(()=>{
                  const f=[...document.querySelectorAll('.mfield')];
                  return {title:$('#sheetTitle').textContent,
                          sub:document.querySelector('#sheetBody .shead').textContent,
                          n:f.length,
                          vals:f.map(x=>x.querySelector('input').value),
                          ro:f.map(x=>x.querySelector('input').readOnly),
                          ok:$('#sheetOk').hidden};})()""")
                print("  edit: %r" % ed)
                checks += [
                    ("titulo «Editar modelo» y subtitulo con el nombre",
                     ed["title"] == "Editar modelo" and "Qwen3 8B" in ed["sub"]),
                    ("cuatro campos, en orden", ed["n"] == 4),
                    ("carga los valores existentes",
                     ed["vals"] == ["32768", "4096", "qwen3-8b", "text"]),
                    ("id y modalidades de solo lectura",
                     ed["ro"] == [False, False, True, True]),
                    ("sin cambios no hay check", ed["ok"] is True),
                ]

                # cambiar un valor invalido: el check no aparece
                await js("""(()=>{
                  const f=document.querySelectorAll('.mfield input');
                  f[0].value='abc'; f[0].dispatchEvent(new Event('input'));})()""")
                await asyncio.sleep(0.1)
                checks.append(("valor no numerico: sin check",
                               (await js("$('#sheetOk').hidden")) is True))

                # un cambio valido hace aparecer el check
                await js("""(()=>{
                  const f=document.querySelectorAll('.mfield input');
                  f[0].value='65536'; f[0].dispatchEvent(new Event('input'));})()""")
                await asyncio.sleep(0.1)
                okvis = (await js("$('#sheetOk').hidden")) is False
                print("  check visible: %s" % okvis)
                checks.append(("cambio valido: aparece el check", okvis))

                # el check abre el dialogo de confirmacion
                await js("$('#sheetOk').click()")
                await asyncio.sleep(0.15)
                dlg = await js("""(()=>{
                  return {open:$('#modal').classList.contains('open'),
                          t:$('#modalTitle').textContent,
                          b:$('#modalBody').innerHTML,
                          ok:$('#modalOk').textContent,
                          no:$('#modalNo').textContent};})()""")
                print("  dialogo: %r" % dlg)
                checks += [
                    ("dialogo «¿Confirmar cambios?»",
                     dlg["open"] is True and dlg["t"] == "¿Confirmar cambios?"),
                    ("avisa de models.json y del reinicio, en cursiva",
                     "<em>models.json</em>" in dlg["b"]
                     and "reiniciar pi remote" in dlg["b"]),
                    ("botones cancelar/Confirmar",
                     dlg["no"] == "cancelar" and dlg["ok"] == "Confirmar"),
                ]

                # cancelar: nada se escribe
                await js("$('#modalNo').click()")
                await asyncio.sleep(0.1)
                d0 = json.loads(models.read_text(encoding="utf-8"))
                checks.append(("cancelar no toca el fichero",
                               d0["providers"]["local"]["models"][0]
                               ["contextWindow"] == 32768))

                # confirmar: se escribe y vuelve a la card de modelos
                await js("ws.onmessage = window.__om;")   # rpc de vuelta real
                await js("$('#sheetOk').click()")
                await asyncio.sleep(0.15)
                await js("$('#modalOk').click()")
                await asyncio.sleep(0.8)
                d1 = json.loads(models.read_text(encoding="utf-8"))
                m = d1["providers"]["local"]["models"][0]
                back = await js("""(()=>{
                  return [$('#sheetTitle').textContent,
                          !!document.querySelector('#sheetBody .mrow small')];})()""")
                print("  escrito: %r, vuelta: %r" % (m["contextWindow"], back))
                checks += [
                    ("confirmar escribe models.json", m["contextWindow"] == 65536),
                    ("vuelve a la card de modelos",
                     back[0] == "Modelo" and back[1] is True),
                ]
    return checks


async def main():
    return backend() + await ui()


raise SystemExit(report(asyncio.run(main())))
