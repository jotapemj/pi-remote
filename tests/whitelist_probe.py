"""Whitelist del picker: rutas permitidas que salen de la lista negra.
El temp del sistema va fijo (los tests viven alli); las del usuario se
anaden y quitan por WS con round-trip en allowed_dirs.json."""
import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

from harness import Bridge, Page, report

# zona de trabajo en la raiz del disco: fuera del temp (que ahora
# esta permitido) para poder medir lo que sigue bloqueado
# zona de trabajo dentro de AppData: una zona bloqueada de verdad, que
# la whitelist debe desbloquear. Sin ella, todo aqui cae en la guarda.
WSROOT = Path.home() / "AppData" / "Local" / "pi_whitelist_probe"


class Area:
    def __enter__(self):
        shutil.rmtree(WSROOT, ignore_errors=True)
        WSROOT.mkdir(parents=True)
        return str(WSROOT)

    def __exit__(self, *a):
        shutil.rmtree(WSROOT, ignore_errors=True)


def backend():
    import pi_web_bridge as B
    checks = []
    with Area() as td:
        root = Path(td) / "zona"
        (root / "dentro").mkdir(parents=True)
        sibling = Path(td) / "hermana"
        sibling.mkdir()
        B.AGENT_DIR = Path(td)
        try:
            # el temp del sistema pasa siempre, sin fichero de whitelist
            checks.append(("temp del sistema: no bloqueado",
                           not B.is_blocked(tempfile.gettempdir())))
            # la zona bajo el temp sigue estando dentro de AppData en
            # Windows: sin whitelist de usuario, un hermano del temp queda
            # fuera (no se abre el resto de la zona)
            checks.append(("prefijo estricto: C:\ no pasa por el temp",
                           B.is_blocked("C:\Windows")))
            # anadir una ruta: ella y sus hijas pasan
            err = B.add_allowed(str(root))
            checks += [
                ("add_allowed sin error", err is None),
                ("la ruta pasa", not B.is_blocked(str(root))),
                ("las hijas pasan", not B.is_blocked(str(root / "dentro"))),
                ("el hermano sigue bloqueado (AppData)", B.is_blocked(str(sibling))),
            ]
            # round-trip y duplicados
            err = B.add_allowed(str(root))
            lst = json.loads((Path(td) / "allowed_dirs.json").read_text(encoding="utf-8"))
            checks += [
                ("el fichero tiene una sola entrada", len(lst) == 1),
                ("el duplicado no se anade dos veces", err is None),
            ]
            # errores
            checks += [
                ("directorio inexistente da error",
                 "not a directory" in B.add_allowed(str(sibling / "no"))),
            ]
            # read_allowed: fija primero, luego la del usuario
            rl = B.read_allowed()
            checks += [
                ("la fija va primera",
                 rl and rl[0]["fixed"] is True
                 and rl[0]["path"].lower() == str(Path(tempfile.gettempdir()).resolve()).lower()),
                ("la del usuario va detras",
                 any(not x["fixed"] and x["path"] == str(root) for x in rl)),
            ]
            # quitar: la del usuario se va, la fija queda
            err = B.remove_allowed(str(root))
            checks += [
                ("remove sin error", err is None),
                ("la ruta vuelve a bloquearse", B.is_blocked(str(root))),
                ("la fija sigue viva",
                 not B.is_blocked(tempfile.gettempdir())
                 and any(x["fixed"] for x in B.read_allowed())),
            ]
        finally:
            del B.AGENT_DIR
    return checks


async def ui():
    checks = []
    with Area() as td:
        # fuera del temp (que es la fila fija): AppData directo, zona
        # bloqueada que solo la whitelist abre
        zone = Path.home() / "AppData" / "Local" / "pi_whitelist_ui"
        shutil.rmtree(zone, ignore_errors=True)
        shutil.rmtree(zone, ignore_errors=True)
        zone.mkdir(parents=True)
        with Bridge(extra={"PI_AGENT_DIR": td}):
            async with Page(port=9386) as p:
                js = p.js
                await p.go()
                # capturar las respuestas rpc que el puente manda de verdad
                await js("window.__rpcs=[]; const __om=ws.onmessage;"
                         " ws.onmessage=e=>{const m=JSON.parse(e.data);"
                         " if(m.type==='rpc')__rpcs.push(m);"
                         " __om && __om.call(ws, e);};")

                def last(cmd):
                    return js("__rpcs.filter(m=>m.command==='%s').pop()" % cmd)

                r = await js("(async()=>{send({type:'whitelist_get'});"
                                    " await new Promise(r=>setTimeout(r,200));"
                                    " return __rpcs.filter(m=>m.command==='whitelist_get').pop();})()")
                dirs = (r or {}).get("data", {}).get("dirs") or []
                checks.append(("whitelist_get: la fija esta",
                               any(d.get("fixed") for d in dirs)))

                zonejs = json.dumps(str(zone))
                r = await js("(async()=>{send({type:'whitelist_add', path:%s});"
                                    " await new Promise(r=>setTimeout(r,200));"
                                    " return __rpcs.filter(m=>m.command==='whitelist_add').pop();})()" % zonejs)
                d = (r or {}).get("data") or {}
                checks.append(("whitelist_add sin error", not d.get("error")))
                checks.append(("el add devuelve la lista ya con la ruta",
                               any(x["path"] == str(zone) for x in (r or {}).get("dirs", []))))

                r = await js("(async()=>{send({type:'whitelist_remove', path:%s});"
                                    " await new Promise(r=>setTimeout(r,200));"
                                    " return __rpcs.filter(m=>m.command==='whitelist_remove').pop();})()" % zonejs)
                dirs = (r or {}).get("dirs") or []
                checks.append(("el remove deja la lista sin la ruta",
                               not any(x["path"] == str(zone) for x in dirs)))

                # la decision vivio en allowed_dirs.json del agente de prueba
                af = Path(td) / "allowed_dirs.json"
                checks.append(("allowed_dirs.json escrito por el puente",
                               af.exists()))

                # ---- UI: fila en pi remote settings, pagina con la lista ----
                # el idioma se fija antes de pintar ninguna hoja
                await js("setLang('en')")
                await js("paintSheet('premote')")
                has = await js("[...document.querySelectorAll('#sheetBody .pick')]"
                               ".some(b => /Trusted paths/i.test(b.textContent))")
                checks.append(("pi remote settings lista 'Trusted paths'",
                               has is True))
                await js("(async()=>{[...document.querySelectorAll('#sheetBody .pick')]"
                         ".find(b => /Trusted paths/i.test(b.textContent)).click();"
                         " await new Promise(r=>setTimeout(r,400));})()")
                checks.append(("la pagina lleva el titulo",
                               (await js("document.querySelector('#sheetTitle').textContent"))
                               == "Trusted paths"))

                # sembrar una entrada de usuario para verla en la lista
                r = await js("(async()=>{send({type:'whitelist_add', path:%s});"
                             " await new Promise(r=>setTimeout(r,200));"
                             " return __rpcs.filter(m=>m.command==='whitelist_add').pop();})()" % zonejs)
                rows = await js("[...document.querySelectorAll('#sheetBody .wrow')]"
                                ".map(x => x.textContent.split(String.fromCharCode(92)).join('/'))")
                checks.append(("la fila fija esta",
                               any(tempfile.gettempdir().replace("\\", "/") in x
                                   for x in rows)))
                checks.append(("la fila de usuario esta",
                               any(str(zone).replace("\\", "/") in x for x in rows)))
                fixed = await js("[...document.querySelectorAll('#sheetBody .wrow')]"
                                 ".find(x => x.classList.contains('fixed'))")
                fixeddel = await js("[...document.querySelectorAll('#sheetBody .wrow')]"
                                    ".filter(x => x.classList.contains('fixed'))"
                                    ".every(x => !x.querySelector('.trashb'))")
                checks.append(("la fija va atenuada y sin papelera",
                               fixed is not None and fixeddel is True))
                delcount = await js("[...document.querySelectorAll('#sheetBody .wrow')]"
                                    ".filter(x => !x.classList.contains('fixed'))"
                                    ".length")
                checks.append(("la de usuario tiene fila editable", delcount == 1))

                # quitar la de usuario desde la fila: desaparece de la lista
                await js("[...document.querySelectorAll('#sheetBody .wrow')]"
                         ".filter(x => !x.classList.contains('fixed'))"
                         ".map(x => x.querySelector('.trashb'))[0].click()")
                # esperar a que el remove asiente: poll hasta 2 s
                await js("""(async()=>{
                  const z = %s; let t=0;
                  while(t<2000){
                    if(![...document.querySelectorAll('#sheetBody .wrow .wpath')]
                       .some(x => x.textContent.includes(z))) return;
                    await new Promise(r=>setTimeout(r,100)); t+=100; }
                })()""" % json.dumps(str(zone)))
                rows = await js("[...document.querySelectorAll('#sheetBody .wrow')]"
                                ".map(x => x.textContent.split(String.fromCharCode(92)).join('/'))")
                checks.append(("tras quitar, la fila de usuario desaparece",
                               not any(str(zone).replace("\\", "/") in x for x in rows)))
    return checks


async def main():
    return backend() + await ui()


raise SystemExit(report(asyncio.run(main())))
