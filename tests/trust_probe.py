"""Trust y settings por proyecto: el puente pregunta la decision guardada
(subiendo del proyecto a la raiz), escribe trust.json con round-trip, y
fusiona claves en .pi/settings.json (None borra la clave). Sin decision de
confianza, pi ignora los recursos locales del proyecto en modo RPC."""
import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from harness import Bridge, Page, report

# en el temp del sistema: zona bloqueada por AppData, pero el temp va
# fijo en la whitelist del puente (y esa es parte de lo que se mide)
TMP = Path(tempfile.gettempdir()) / "trust_probe_tmp"


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
        (root / "sub").mkdir(parents=True)
        B.AGENT_DIR = Path(td)
        try:
            # sin decision guardada
            d, at = B.trust_decision(str(root))
            checks.append(("sin decision: None", d is None and at is None))
            # trust en la propia carpeta
            err = B.set_trust(str(root), True)
            d, at = B.trust_decision(str(root))
            checks += [
                ("set_trust sin error", err is None),
                ("decision propia: True", d is True and at == str(root.resolve())),
            ]
            # la decision del hijo manda sobre la del padre
            err = B.set_trust(str(root / "sub"), False)
            d, at = B.trust_decision(str(root / "sub"))
            checks += [
                ("el hijo manda sobre el padre", d is False),
                ("round-trip: la entrada del padre intacta",
                 str(root.resolve()) in json.loads(
                     (Path(td) / "trust.json").read_text(encoding="utf-8"))),
            ]
            # sin decision en toda la cadena
            other = Path(td) / "otro"
            other.mkdir()
            d, at = B.trust_decision(str(other))
            checks.append(("otra carpeta: None", d is None and at is None))
            # errores
            checks += [
                ("directorio inexistente da error",
                 "not a directory" in B.set_trust(str(other / "no"), True)),
                ("path bloqueado da error",
                 "blocked" in B.set_trust("C:\\Windows", True)),
            ]
            # settings por proyecto: fusion y borrado de clave
            err = B.save_project_settings(str(root), {"defaultModel": "a"})
            s = B.read_project_settings(str(root))
            checks.append(("escribe .pi/settings.json",
                           err is None and s.get("defaultModel") == "a"))
            err = B.save_project_settings(
                str(root), {"defaultThinkingLevel": "medium"})
            s = B.read_project_settings(str(root))
            checks.append(("fusion: las dos claves conviven",
                           s.get("defaultModel") == "a"
                           and s.get("defaultThinkingLevel") == "medium"))
            err = B.save_project_settings(str(root), {"defaultModel": None})
            s = B.read_project_settings(str(root))
            checks.append(("None borra la clave",
                           "defaultModel" not in s
                           and s.get("defaultThinkingLevel") == "medium"))
            checks.append(("carpeta inexistente da error",
                           "not a directory" in B.save_project_settings(
                               str(root / "no"), {"x": 1})))
        finally:
            del B.AGENT_DIR
    return checks


async def ui():
    checks = []
    with Area() as td:
        proj = Path(td) / "proj"
        proj.mkdir()
        with Bridge(extra={"PI_AGENT_DIR": td}):
            async with Page(port=9385) as p:
                js = p.js
                await p.go()
                # capturar las respuestas rpc que el puente manda de verdad
                await js("window.__rpcs=[]; const __om=ws.onmessage;"
                         " ws.onmessage=e=>{const m=JSON.parse(e.data);"
                         " if(m.type==='rpc')__rpcs.push(m);};")
                projjs = json.dumps(str(proj))

                await js("send({type:'trust_status', path:%s})" % projjs)
                await asyncio.sleep(0.3)
                r = await js("__rpcs.find(m=>m.command==='trust_status')")
                checks.append(("trust_status sin decision",
                               r and r["data"]["decision"] is None))

                await js("send({type:'trust_set', path:%s, decision:true})" % projjs)
                await asyncio.sleep(0.3)
                r = await js("__rpcs.find(m=>m.command==='trust_set')")
                checks.append(("trust_set sin error",
                               r and not r["data"].get("error")))

                r = await js("(async()=>{send({type:'trust_status', path:%s});"
                             " await new Promise(r=>setTimeout(r,200));"
                             " return __rpcs.filter(m=>m.command==='trust_status')"
                             ".pop();})()" % projjs)
                checks.append(("la decision queda guardada",
                               r and r["data"]["decision"] is True))

                await js("send({type:'project_settings_save', cwd:%s,"
                         " settings:{defaultModel:'swift/swift-27b'}})" % projjs)
                await asyncio.sleep(0.3)
                r = await js("__rpcs.find(m=>m.command==='project_settings_save')")
                checks.append(("project_settings_save sin error",
                               r and not r["data"].get("error")))

                r = await js("(async()=>{send({type:'project_settings_get', cwd:%s});"
                             " await new Promise(r=>setTimeout(r,200));"
                             " return __rpcs.filter(m=>m.command==='project_settings_get')"
                             ".pop();})()" % projjs)
                checks.append(("project_settings_get devuelve el override",
                               r and r["data"]["settings"].get("defaultModel")
                               == "swift/swift-27b"))

                # la decision vivio en el trust.json del agente de prueba
                tf = Path(td) / "trust.json"
                raw = tf.read_text(encoding="utf-8") if tf.exists() else ""
                checks.append(("trust.json escrito por el puente",
                               json.dumps(str(proj.resolve())) in raw))
    return checks


async def main():
    return backend() + await ui()


raise SystemExit(report(asyncio.run(main())))
