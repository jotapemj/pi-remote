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

    # override por modelo: merge anidado en settings.json
    with tempfile.TemporaryDirectory() as td2:
        B.AGENT_DIR = Path(td2)
        try:
            err = B.save_model_thinking_level("swift/b", "xhigh")
            d = json.loads((Path(td2) / "settings.json")
                           .read_text(encoding="utf-8"))
            checks.append(("modelThinkingLevel se escribe sin error",
                           err is None
                           and d["modelThinkingLevels"]["swift/b"] == "xhigh"))
            # null borra la entrada y limpia el mapa vacio
            err = B.save_model_thinking_level("swift/b", None)
            d = json.loads((Path(td2) / "settings.json")
                           .read_text(encoding="utf-8"))
            checks.append(("null borra la entrada y el mapa",
                           err is None
                           and "modelThinkingLevels" not in d))
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

                # abrir la pagina Models; la lista se inyecta (fake_pi
                # trae su propia) y coincide con lo que hay en models.json
                await js("menuSheet()")
                await asyncio.sleep(0.1)
                await js("paintSheet('pagent')")
                await asyncio.sleep(0.1)
                await js("paintSheet('models')")
                await js("onRpc({command:'get_available_models', data:{models:["
                         "{id:'qwen3-8b',name:'Qwen3 8B',provider:'local',"
                         "contextWindow:32768,maxTokens:4096,input:['text']}]}})")
                await asyncio.sleep(0.2)

                # cada fila lleva lapiz y papelera; la primera fila es anadir
                pens = await js("""(()=>{
                  const b=[...document.querySelectorAll('#sheetBody .mrow')];
                  return {n:b.length,
                          pen:b.filter(x=>x.querySelector('.pen svg')).length,
                          add:!!document.querySelector('#sheetBody .pick'),
                          title:$('#sheetTitle').textContent};})()""")
                print("  filas: %r" % pens)
                checks += [
                    ("la pagina Models lista el modelo", pens["n"] == 1),
                    ("cada fila lleva el lapiz y la primera es anadir",
                     pens["pen"] == 1 and pens["add"] is True),
                ]

                # en global la lista es solo eleccion: sin lapiz ni papelera
                await js("paintSheet('modelList')")
                await asyncio.sleep(0.2)
                nopens = await js("(()=>{" + """
                  const b=[...document.querySelectorAll('#sheetBody .mrow')];
                  return {n:b.length,
                          pen:b.filter(x=>x.querySelector('.pen')).length};})()""")
                checks.append(("global: solo eleccion, sin lapiz",
                               nopens["n"] == 1 and nopens["pen"] == 0))
                await js("paintSheet('models')")
                await asyncio.sleep(0.2)

                # pulsar el lapiz abre modelEdit con los valores cargados
                await js("document.querySelector('#sheetBody .mrow .pen').click()")
                await asyncio.sleep(0.4)
                ed = await js("""(()=>{
                  // .sel son los campos de eleccion: no llevan input
                  const f=[...document.querySelectorAll('.mfield')]
                    .filter(x=>x.querySelector('input'));
                  return {title:$('#sheetTitle').textContent,
                          sub:document.querySelector('#sheetBody .shead').textContent,
                          n:f.length,
                          vals:f.map(x=>x.querySelector('input').value),
                          ro:f.map(x=>x.querySelector('input').readOnly),
                          think:(document.querySelectorAll('.mfield.sel')[0].querySelector('.pval')||{}).textContent,
                          ok:$('#sheetOk').hidden};})()""")
                print("  edit: %r" % ed)
                checks += [
                    ("titulo «Editar modelo» y subtitulo con el nombre",
                     ed["title"] == "Editar modelo" and "Qwen3 8B" in ed["sub"]),
                    # las modalidades pasaron de campo de solo lectura a
                    # interruptor: si cambia el servidor donde corre el modelo
                    # (gana o pierde vision) hay que poder corregirlas. El id
                    # sigue bloqueado: es la clave con la que pi lo encuentra
                    ("tres campos, en orden", ed["n"] == 3),
                    ("razonamiento por modelo: «Usar global» sin override",
                     ed["think"] == "Usar global"),
                    ("carga los valores existentes",
                     ed["vals"] == ["32768", "4096", "qwen3-8b"]),
                    ("solo el id es de solo lectura",
                     ed["ro"] == [False, False, True]),
                    ("sin cambios no hay check", ed["ok"] is True),
                ]

                # escala de los campos: 14 px como las filas de ajustes (el
                # zoom al enfocar no existe, el viewport lleva maximum-scale=1)
                # y rotulo discreto: gris en reposo, acento solo con el foco,
                # sin mayusculas. Headless no tiene foco de sistema: sin la
                # emulacion, :focus no aplicaria y se mediria el reposo
                await p.cmd("Emulation.setFocusEmulationEnabled", enabled=True)
                sc = await js("""(async () => {
                  const i = document.querySelector('#sheetBody .mfield input:not([readonly])');
                  const l = i.nextElementSibling;
                  const cs = e => getComputedStyle(e);
                  const probe = document.createElement('span');
                  probe.style.color = 'var(--amber)';
                  document.body.appendChild(probe);
                  const amber = cs(probe).color;
                  const dim = (probe.style.color = 'var(--dim)', cs(probe).color);
                  probe.remove();
                  const rest = cs(l).color;
                  i.focus();
                  await new Promise(r => setTimeout(r, 300));
                  const foc = cs(l).color;
                  i.blur();
                  const sel = document.querySelector('.mfield.sel button');
                  return {fs: cs(i).fontSize, selFs: cs(sel).fontSize,
                    tt: cs(l).textTransform, rest, foc, amber, dim,
                    // ::first-letter no sale en getComputedStyle: se mide
                    // el ancho pintado contra la palabra en mayuscula y en
                    // minuscula, con la misma fuente
                    cap: (() => {
                      const s0 = sel.firstElementChild, t = s0.textContent;
                      const w = x => { const k = document.createElement('span');
                        k.style.cssText = 'position:absolute;visibility:hidden;'
                          + 'white-space:nowrap;font:' + cs(s0).font;
                        k.textContent = x; document.body.appendChild(k);
                        const v = k.getBoundingClientRect().width; k.remove();
                        return v; };
                      const got = s0.getBoundingClientRect().width;
                      const up = w(t[0].toUpperCase() + t.slice(1));
                      const low = w(t[0].toLowerCase() + t.slice(1));
                      return Math.abs(got - up) < 0.5 && Math.abs(up - low) > 0.5
                        ? 'uppercase' : 'none'; })()};
                })()""")
                print("  escala: %r" % sc)
                checks += [
                    ("campos a 14 px, eleccion igual",
                     sc["fs"] == "14px" and sc["selFs"] == "14px"),
                    ("rotulo gris en reposo, acento con el foco",
                     sc["rest"] == sc["dim"] and sc["foc"] == sc["amber"]),
                    ("rotulo sin mayusculas", sc["tt"] == "none"),
                    ("el campo de eleccion empieza en mayuscula",
                     sc["cap"] == "uppercase"),
                ]

                # el campo abre una pagina de sheet, no un modal centrado
                # los niveles llegan por onRpc (sincrono): si el clic llegara
                # antes que la respuesta, la pagina saldria en estado de carga
                await js("onRpc({command:'get_available_thinking_levels',"
                         " data:{levels:['off','medium','high']}})")
                await asyncio.sleep(0.3)
                await js("document.querySelectorAll('.mfield.sel button')[0].click()")
                await asyncio.sleep(0.3)
                pg = await js("""(()=>{
                  const b=[...document.querySelectorAll('#sheetBody .mrow')];
                  return {title:$('#sheetTitle').textContent,
                          n:b.length, first:b[0].textContent.trim(),
                          modal:$('#modal').classList.contains('open'),
                          help:!!document.querySelector('#sheetBody .chelp')};})()""")
                checks += [
                    ("razonamiento por modelo abre una pagina de sheet",
                     pg["title"].lower() == "razonamiento del modelo"
                     and pg["modal"] is False),
                    ("fila «Usar global» arriba y nota de reinicio",
                     pg["n"] == 4 and pg["first"] == "Usar global"
                     and pg["help"] is True),
                ]
                # elegir un nivel: staged, vuelve al formulario y sale el check
                await js("document.querySelectorAll('#sheetBody .mrow')[3].click()")
                await asyncio.sleep(0.3)
                st = await js("""(()=>{
                  return {think:(document.querySelectorAll('.mfield.sel')[0].querySelector('.pval')||{}).textContent,
                          ok:$('#sheetOk').hidden, sp:sheetPage,
                          stg:thinkStaged, mt:modelThinking};})()""")
                checks.append(("elegir un nivel vuelve al formulario con el check",
                               st["think"] == "high" and st["ok"] is False))
                # y «Usar global» lo descarta: sin check
                await js("document.querySelectorAll('.mfield.sel button')[0].click()")
                await asyncio.sleep(0.3)
                await js("document.querySelector('#sheetBody .mrow').click()")
                await asyncio.sleep(0.3)
                st2 = await js("""(()=>{
                  return {think:(document.querySelectorAll('.mfield.sel')[0].querySelector('.pval')||{}).textContent,
                          ok:$('#sheetOk').hidden, sp:sheetPage,
                          st:thinkStaged, mt:modelThinking};})()""")
                checks.append(("«Usar global» descarta el staged",
                               st2["think"] == "Usar global" and st2["ok"] is True))

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
                    ("vuelve a la pagina Models",
                     back[0] == "Modelos" and back[1] is True),
                ]

                # atras por niveles: modelEdit -> model -> raiz
                await js("document.querySelector('#sheetBody .mrow .pen').click()")
                await asyncio.sleep(0.4)
                await js("$('#sheetBack').click()")
                await asyncio.sleep(0.4)
                t1 = await js("$('#sheetTitle').textContent")
                await js("$('#sheetBack').click()")
                await asyncio.sleep(0.4)
                t2 = await js("$('#sheetTitle').textContent")
                print("  atras: %r -> %r" % (t1, t2))
                checks += [
                    ("atras desde modelEdit vuelve a Models",
                     t1 == "Modelos"),
                    ("atras desde Models vuelve a la raiz del menu",
                     t2 == "men\u00fa"),
                ]
    return checks


async def main():
    return backend() + await ui()


raise SystemExit(report(asyncio.run(main())))
