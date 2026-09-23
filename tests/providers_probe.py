"""Providers en models.json: ver, editar y añadir desde la web. El puente
nunca expone el valor de la clave (solo un flag) y todo cambio avisa de que
se aplica al reiniciar (/restart)."""
import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

from harness import Bridge, Page, WS_URL, report

TMP = Path(tempfile.gettempdir()) / "providers_probe_tmp"


class Area:
    def __enter__(self):
        shutil.rmtree(TMP, ignore_errors=True)
        TMP.mkdir(parents=True)
        return str(TMP)

    def __exit__(self, *a):
        shutil.rmtree(TMP, ignore_errors=True)


SEED = {"providers": {"local": {
    "baseUrl": "http://x:1/v1", "api": "openai-completions",
    "apiKey": "secreta",
    "models": [{"id": "qwen3-8b", "name": "Qwen3 8B"}]}}}


def backend():
    import pi_web_bridge as B
    checks = []
    with Area() as td:
        mj = Path(td) / "models.json"
        os.environ["PI_MODELS_JSON"] = str(mj)
        try:
            checks.append(("sin fichero: lista vacia",
                           B.providers_get() == []))
            mj.write_text(json.dumps(SEED), encoding="utf-8")
            lst = B.providers_get()
            checks += [
                ("sale el provider con url, api y modelos",
                 lst == [{"id": "local", "baseUrl": "http://x:1/v1",
                          "api": "openai-completions", "hasKey": True,
                          "models": ["Qwen3 8B"]}]),
                ("la clave no viaja en la lista",
                 "secreta" not in json.dumps(lst)),
            ]
            err = B.provider_save("local", "http://y:2/v1", None)
            d = json.loads(mj.read_text(encoding="utf-8"))
            checks += [
                ("save cambia la url", err is None
                 and d["providers"]["local"]["baseUrl"] == "http://y:2/v1"),
                ("save conserva el resto del fichero",
                 d["providers"]["local"]["models"][0]["id"] == "qwen3-8b"
                 and d["providers"]["local"]["apiKey"] == "secreta"),
                ("save de inexistente da error",
                 B.provider_save("nope", "http://z", None) is not None),
            ]
            checks.append(("add con id invalido da error",
                           B.provider_add("a b", "http://x",
                                          "openai-completions", None)
                           is not None))
            err = B.provider_add("nuevo", "http://n:3/v1",
                                 "openai-completions", "k")
            d = json.loads(mj.read_text(encoding="utf-8"))
            checks += [
                ("add crea el provider con su clave", err is None
                 and d["providers"]["nuevo"]["baseUrl"] == "http://n:3/v1"
                 and d["providers"]["nuevo"]["apiKey"] == "k"),
                ("add duplicado da error",
                 B.provider_add("nuevo", "http://x",
                                "openai-completions", None) is not None),
            ]
            err = B.model_add("local", "qwen3-14b", "Qwen3 14B", 32768,
                              8192, True)
            d = json.loads(mj.read_text(encoding="utf-8"))
            m = d["providers"]["local"]["models"][-1]
            checks += [
                ("model_add añade el modelo completo", err is None
                 and m == {"id": "qwen3-14b", "name": "Qwen3 14B",
                           "contextWindow": 32768, "maxTokens": 8192,
                           "reasoning": True}),
                ("model_add duplicado da error",
                 B.model_add("local", "qwen3-14b", None, 1000, 100,
                             False) is not None),
                ("model_add id invalido da error",
                 B.model_add("local", "a/b", None, 1000, 100, False)
                 is not None),
                ("model_add a provider inexistente da error",
                 B.model_add("nope", "m", None, 1000, 100, False)
                 is not None),
            ]
        finally:
            os.environ.pop("PI_MODELS_JSON", None)
    return checks


async def ui():
    checks = []
    with Area() as td:
        mj = Path(td) / "models.json"
        mj.write_text(json.dumps(SEED), encoding="utf-8")
        with Bridge(extra={"PI_AGENT_DIR": td,
                           "PI_MODELS_JSON": str(mj)}):
            async with Page(port=9386) as p:
                js = p.js
                await p.go()
                await js("setLang('en')")

                # ---- la pagina lista el provider sembrado ----
                await js("turnTo('providers', -1)")
                await asyncio.sleep(0.6)
                rows = await js("""[...document.querySelectorAll('#sheetBody .prow')]
                  .map(r=>r.textContent)""")
                checks += [
                    ("la lista muestra el provider",
                     any("local" in r for r in rows)),
                    ("con su url y sus modelos",
                     any("http://x:1/v1" in r and "Qwen3 8B" in r
                         for r in rows)),
                ]

                # ---- añadir: formulario, aviso de reinicio, lista nueva ----
                await js("""(()=>{[...document.querySelectorAll('#sheetBody .pick')]
                  .find(b=>/Add provider/.test(b.textContent)).click();})()""")
                await asyncio.sleep(0.5)
                okvis = await js("""(()=>{
                  const ins=[...document.querySelectorAll(
                    '#sheetBody .mfield input')];
                  ins[0].value='nuevo2';
                  ins[0].dispatchEvent(new Event('input'));
                  ins[1].value='http://n:9/v1';
                  ins[1].dispatchEvent(new Event('input'));
                  return $('#sheetOk').hidden;})()""")
                checks.append(("el check aparece con id y url",
                               okvis is False))
                await js("$('#sheetOk').click()")
                await asyncio.sleep(0.15)
                dlg = await js("""({t:$('#modalTitle').textContent,
                  b:$('#modalBody').innerHTML})""")
                checks.append(("avisa que aplica al reiniciar",
                               "restart" in dlg["b"]))
                await js("$('#modalOk').click()")
                ok = await js("""(async()=>{
                  for(let i=0;i<50;i++){
                    if([...document.querySelectorAll('#sheetBody .prow')]
                      .some(r=>/nuevo2/.test(r.textContent))) return true;
                    await new Promise(r=>setTimeout(r,100));
                  }
                  return false;})()""")
                checks.append(("el nuevo provider sale en la lista",
                               bool(ok)))

                # ---- editar: cambiar la url del provider sembrado ----
                await js("""(()=>{[...document.querySelectorAll('#sheetBody .prow')]
                  .find(r=>/local/.test(r.textContent))
                  .click();})()""")
                await asyncio.sleep(0.5)
                await js("""(()=>{const ins=[...document.querySelectorAll(
                  '#sheetBody .mfield input')];
                  ins[0].value='http://y:7/v1';
                  ins[0].dispatchEvent(new Event('input'));})()""")
                await js("$('#sheetOk').click()")
                await asyncio.sleep(0.15)
                await js("$('#modalOk').click()")
                ok = await js("""(async()=>{
                  for(let i=0;i<50;i++){
                    if([...document.querySelectorAll('#sheetBody .prow')]
                      .some(r=>/http:\\/\\/y:7\\/v1/.test(r.textContent)))
                      return true;
                    await new Promise(r=>setTimeout(r,100));
                  }
                  return false;})()""")
                checks.append(("la url editada sale en la lista", bool(ok)))
                d = json.loads(mj.read_text(encoding="utf-8"))
                checks += [
                    ("el fichero trae la nueva url",
                     d["providers"]["local"]["baseUrl"] == "http://y:7/v1"),
                    ("la clave sigue intacta en disco",
                     d["providers"]["local"]["apiKey"] == "secreta"),
                ]

                # ---- añadir modelo desde la pagina de edicion ----
                await js("""(()=>{[...document.querySelectorAll('#sheetBody .prow')]
                  .find(r=>/local/.test(r.textContent))
                  .click();})()""")
                await asyncio.sleep(0.5)
                hasbtn = await js("""[...document.querySelectorAll(
                  '#sheetBody .pick')].some(b=>/Add model/.test(
                  b.textContent))""")
                checks.append(("la pagina de edicion ofrece 'Add model'",
                               bool(hasbtn)))
                await js("""(()=>{[...document.querySelectorAll('#sheetBody .pick')]
                  .find(b=>/Add model/.test(b.textContent)).click();})()""")
                await asyncio.sleep(0.5)
                okvis = await js("""(()=>{
                  const ins=[...document.querySelectorAll(
                    '#sheetBody .mfield input')];
                  ins[0].value='qwen3-14b';
                  ins[0].dispatchEvent(new Event('input'));
                  ins[2].value='32768';
                  ins[2].dispatchEvent(new Event('input'));
                  ins[3].value='8192';
                  ins[3].dispatchEvent(new Event('input'));
                  return $('#sheetOk').hidden;})()""")
                checks.append(("el check exige id y numeros", okvis is False))
                await js("$('#sheetOk').click()")
                await asyncio.sleep(0.15)
                await js("$('#modalOk').click()")
                ok = await js("""(async()=>{
                  for(let i=0;i<50;i++){
                    if([...document.querySelectorAll('#sheetBody .prow')]
                      .some(r=>/qwen3-14b/.test(r.textContent))) return true;
                    await new Promise(r=>setTimeout(r,100));
                  }
                  return false;})()""")
                checks.append(("el nuevo modelo sale en la fila del provider",
                               bool(ok)))

                # ---- el tipo de API se elige, no se teclea ----
                await js("sheetStack=[]; paintSheet('provAdd')")
                await asyncio.sleep(0.3)
                # el campo de API se toca y abre lista, pero tiene que
                # alinearse con los de escribir: una fila de menu entre
                # campos rompia la columna del formulario
                form = await js("""(()=>{
                  const sel=document.querySelector('#sheetBody .mfield.sel');
                  if(!sel) return {found:false};
                  const b=sel.querySelector('button');
                  const txt=document.querySelector('#sheetBody .mfield:not(.sel) input');
                  const rb=b.getBoundingClientRect(), rt=txt.getBoundingClientRect();
                  const cb=getComputedStyle(b), ct=getComputedStyle(txt);
                  return {found:true, val:b.textContent,
                    dx:Math.abs(rb.left-rt.left), dw:Math.abs(rb.width-rt.width),
                    dh:Math.abs(rb.height-rt.height),
                    radio:cb.borderRadius===ct.borderRadius,
                    borde:cb.borderColor===ct.borderColor,
                    chev:!!sel.querySelector('.ch')};})()""")
                checks += [
                    ("el tipo de API es una eleccion, no un campo de texto",
                     form["found"] and form["chev"]
                     and "API type" in form.get("val", "")),
                    ("y se alinea con los campos de al lado",
                     form.get("dx", 9) < 1 and form.get("dw", 9) < 1
                     and form.get("dh", 9) < 2
                     and form.get("radio") and form.get("borde")),
                    ("arranca en la API mas comun en servidores locales",
                     "openai-completions" in form.get("val", "")),
                ]
                await js("goPage('provApi')")
                await asyncio.sleep(0.45)
                apis = await js("""(()=>{
                  const rows=[...document.querySelectorAll('#sheetBody .mrow')];
                  return {list:rows.map(r=>r.textContent.trim()),
                    sel:rows.filter(r=>r.classList.contains('sel'))
                            .map(r=>r.textContent.trim())};})()""")
                checks += [
                    # la lista sale de BUILTIN_APIS de pi-ai, no de una suposicion
                    ("ofrece las diez APIs que pi trae de serie",
                     len(apis["list"]) == 10
                     and "anthropic-messages" in apis["list"]
                     and "google-vertex" in apis["list"]
                     and "bedrock-converse-stream" in apis["list"]),
                    ("con una sola marcada",
                     apis["sel"] == ["openai-completions"]),
                ]
                # una API de extension, fuera de la lista de serie, se respeta
                extra = await js("""(()=>{
                  provDraft.api='mi-api-de-extension';
                  paintSheet('provApi');
                  const rows=[...document.querySelectorAll('#sheetBody .mrow')];
                  return {n:rows.length, first:rows[0].textContent.trim(),
                    sel:rows.filter(r=>r.classList.contains('sel'))
                            .map(r=>r.textContent.trim())};})()""")
                checks.append(
                    ("una API ajena a la lista no se pierde ni se pisa",
                     extra["n"] == 11 and extra["first"] == "mi-api-de-extension"
                     and extra["sel"] == ["mi-api-de-extension"]))

                # ---- modalidades al anadir modelo ----
                await js("sheetStack=[]; provEditId='local';"
                         " paintSheet('modelAdd')")
                await asyncio.sleep(0.3)
                vis = await js("""(()=>{
                  const sws=[...document.querySelectorAll('#sheetBody .sw')];
                  const last=sws[sws.length-1];
                  const before=JSON.stringify(fieldsOfModelAdd());
                  return {n:sws.length, before};})()
                  """.replace("fieldsOfModelAdd()", "[]"))
                # el toggle de vision es el segundo: razonamiento y modalidades
                tog = await js("""(()=>{
                  const sws=[...document.querySelectorAll('#sheetBody .sw')];
                  if(sws.length < 2) return {err:'faltan toggles'};
                  const v=sws[1];
                  v.click();
                  return {on:v.getAttribute('aria-checked'),
                    lbl:v.closest('.swrow').querySelector('.mtxt').textContent};
                  })()""")
                checks += [
                    ("anadir modelo ofrece razonamiento y modalidades",
                     vis["n"] == 2),
                    ("el toggle declara que acepta imagenes",
                     not tog.get("err") and tog["on"] == "true"
                     and tog["lbl"] == "Image"),
                ]
    return checks


async def main():
    return backend() + await ui()


if __name__ == "__main__":
    raise SystemExit(report(asyncio.run(main())))
