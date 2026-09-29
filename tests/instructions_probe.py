"""Instructions: los ficheros que pi mete en su system prompt. Global:
AGENTS.md (o el que pi use en AGENT_DIR) y APPEND_SYSTEM.md; proyecto: el
fichero de contexto de la raiz del cwd y, solo leer, lo que pi carga ademas.
Se edita el fichero que pi usa de verdad (el primero de AGENTS.override.md,
AGENTS.md, CLAUDE.md...): crear un AGENTS.md junto a un CLAUDE.md haria que
pi dejara de leer este. Guardar respeta CRLF y BOM (diff limpio en git).
La interfaz no toca el puente real: los envios se interceptan.
"""
import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from harness import Bridge, Page, report

TMP = Path(tempfile.gettempdir()) / "pi_instr_probe"


def backend():
    import pi_web_bridge as B
    checks = []
    shutil.rmtree(TMP, ignore_errors=True)
    agent = TMP / "agent"
    agent.mkdir(parents=True)
    old = B.AGENT_DIR
    B.AGENT_DIR = agent
    try:
        g = B.instructions_get("global", "")
        checks.append(("global vacio: los dos, sin crear, con su nombre",
                       [(f["kind"], f["name"], f["exists"]) for f in g["files"]]
                       == [("agents", "AGENTS.md", False),
                           ("append", "APPEND_SYSTEM.md", False)]))
        err = B.instructions_save("global", "", "agents", "Hola\nmundo")
        checks.append(("crear AGENTS.md global",
                       err is None and (agent / "AGENTS.md").read_text(
                           encoding="utf-8") == "Hola\nmundo"))
        B.instructions_save("global", "", "append", "Regla")
        g = B.instructions_get("global", "")
        checks.append(("y se lee con su contenido",
                       [f.get("body") for f in g["files"]]
                       == ["Hola\nmundo", "Regla"]))
        # el override le gana, como en pi: se edita ese
        (agent / "AGENTS.override.md").write_text("ov", encoding="utf-8")
        g = B.instructions_get("global", "")
        checks.append(("AGENTS.override.md gana a AGENTS.md",
                       g["files"][0]["name"] == "AGENTS.override.md"))
        (agent / "AGENTS.override.md").unlink()

        # proyecto con CLAUDE.md: se edita ese, NO se crea un AGENTS.md
        root = TMP / "disk"
        proj = root / "work" / "app"
        proj.mkdir(parents=True)
        (root / "AGENTS.md").write_text("arriba", encoding="utf-8")
        claude = proj / "CLAUDE.md"
        claude.write_bytes(b"\xef\xbb\xbfLinea 1\r\nLinea 2\r\n")
        p = B.instructions_get("project", str(proj))
        f = p["files"][0]
        checks += [
            ("proyecto: el CLAUDE.md que pi usa, con su contenido sin BOM",
             f["name"] == "CLAUDE.md" and f["exists"]
             and f["body"] == "Linea 1\nLinea 2\n"),
            ("tambien se cargan: el global y las carpetas superiores",
             [a["name"] for a in p["also"]] == ["AGENTS.md", "AGENTS.md"]
             and p["also"][0].get("global") is True
             and p["also"][1]["path"] == str(root / "AGENTS.md")),
        ]
        B.instructions_save("project", str(proj), "context",
                            "Linea 1\nLinea 2\nLinea 3\n")
        raw = claude.read_bytes()
        checks += [
            ("guardar edita el CLAUDE.md, sin crear AGENTS.md",
             not (proj / "AGENTS.md").exists()),
            ("respeta CRLF y BOM del fichero (diff limpio)",
             raw == b"\xef\xbb\xbfLinea 1\r\nLinea 2\r\nLinea 3\r\n"),
        ]
        # sin fichero: se crea AGENTS.md en la raiz del cwd
        bare = root / "bare"
        bare.mkdir()
        f = B.instructions_get("project", str(bare))["files"][0]
        B.instructions_save("project", str(bare), "context", "x")
        checks += [
            ("sin ninguno: se ofrece AGENTS.md sin crear",
             f["name"] == "AGENTS.md" and not f["exists"]),
            ("y se crea en la raiz del cwd", (bare / "AGENTS.md").is_file()),
        ]
        checks += [
            ("borrar quita el fichero",
             B.instructions_delete("project", str(bare), "context") is None
             and not (bare / "AGENTS.md").exists()),
            ("borrar lo que no existe da error",
             B.instructions_delete("project", str(bare), "context")
             == "not found"),
            ("sin proyecto abierto, error",
             B.instructions_get("project", "").get("error")
             == "no project open"),
            ("tipo desconocido: error, no escribe nada",
             B.instructions_save("global", "", "system", "x") == "bad kind"
             and not (agent / "SYSTEM.md").exists()),
            ("tope de tamano",
             B.instructions_save("global", "", "append", "x" * 600_000)
             == "too long"),
        ]
    finally:
        B.AGENT_DIR = old
        shutil.rmtree(TMP, ignore_errors=True)
    return checks


FILES = [{"kind": "agents", "name": "AGENTS.md",
          "path": "C:/Users/me/.pi/agent/AGENTS.md", "exists": True,
          "body": "Reply in Spanish."},
         {"kind": "append", "name": "APPEND_SYSTEM.md",
          "path": "C:/Users/me/.pi/agent/APPEND_SYSTEM.md", "exists": False}]

# los envios de instrucciones no llegan al puente (que leeria ~/.pi real)
SPY = """(() => {
  window.__sent = [];
  const s0 = ws.send.bind(ws);
  ws.send = x => { const o = JSON.parse(x);
    if(/^instructions_/.test(o.type)){ window.__sent.push(o); return; }
    return s0(x); };
})()"""


async def ui():
    checks = []
    with Bridge():
        async with Page() as p:
            js = p.js
            await p.go()
            await asyncio.sleep(0.8)
            await js("setLang('en')")
            await js(SPY)
            await js("menuSheet(); goPage('model')")
            await asyncio.sleep(0.5)
            card = await js("""[...document.querySelectorAll('#sheetBody .pick')]
              .map(b => b.textContent.trim()).includes('Instructions')""")
            await js("[...document.querySelectorAll('#sheetBody .pick')]"
                     ".find(b => b.textContent.trim() === 'Instructions').click()")
            await asyncio.sleep(0.5)
            asked = await js("window.__sent.map(o => o.type + ':' + o.scope)")
            await js("onRpc({command:'instructions_get', data:{scope:'global',"
                     " files:%s, also:[]}})" % json.dumps(FILES))
            await asyncio.sleep(0.4)
            rows = await js("""[...document.querySelectorAll('#sheetBody .pick')]
              .map(b => b.textContent.trim())""")
            checks += [
                ("card Instructions en global settings", card),
                ("al abrir pide los ficheros globales",
                 "instructions_get:global" in asked),
                ("siempre los dos: el existente con su ruta y el otro sin crear",
                 any(r.startswith("AGENTS.md") and "~/.pi/agent/AGENTS.md" in r
                     or "AGENTS.md" in r for r in rows)
                 and any("APPEND_SYSTEM.md" in r and "not created" in r
                         for r in rows)),
            ]
            # menu de tres puntos: el sin crear no ofrece eliminar
            menus = await js("""(() => {
              const rows = [...document.querySelectorAll('#sheetBody .pick')];
              const out = [];
              rows.forEach(r => { r.querySelector('.dotsb').click();
                const pops = document.querySelectorAll('.ctxpop');
                const pop = pops[pops.length - 1];
                out.push([...pop.querySelectorAll('button, .ci')]
                  .map(x => x.textContent.trim()).filter(Boolean));
                pops.forEach(x => x.remove());
              });
              return out; })()""")
            print("  menus:", menus)
            checks.append(("tres puntos: editar y eliminar; sin crear, solo editar",
                           any("Delete" in m for m in menus[0])
                           and not any("Delete" in m for m in menus[1])))
            # tocar la fila abre el editor con el contenido
            await js("[...document.querySelectorAll('#sheetBody .pick')][0].click()")
            await asyncio.sleep(0.5)
            ed = await js("""(() => { const t = document.querySelector('#sheetBody textarea');
              return {title: $('#sheetTitle').textContent, val: t && t.value,
                      ok: $('#sheetOk').hidden}; })()""")
            await js("""(() => { const t = document.querySelector('#sheetBody textarea');
              t.value += '\\nNew rule.'; t.dispatchEvent(new Event('input')); })()""")
            await asyncio.sleep(0.3)
            okOn = await js("!$('#sheetOk').hidden")
            await js("""(() => { const t = document.querySelector('#sheetBody textarea');
              t.value = 'Reply in Spanish.'; t.dispatchEvent(new Event('input')); })()""")
            await asyncio.sleep(0.05)
            fading = await js("$('#sheetOk').classList.contains('out')")
            await asyncio.sleep(0.3)
            okOff = await js("$('#sheetOk').hidden")
            checks += [
                ("tocar la fila abre el editor con el contenido",
                 ed["title"] == "Instructions" and ed["val"] == "Reply in Spanish."
                 and ed["ok"] is True),
                ("con cambios aparece el check", okOn),
                ("deshacer los cambios lo quita con fundido",
                 fading and okOff),
            ]
            # guardar: dialogo de reinicio y envio del fichero
            await js("""(() => { const t = document.querySelector('#sheetBody textarea');
              t.value = 'Reply in Spanish.\\nNew rule.';
              t.dispatchEvent(new Event('input')); $('#sheetOk').click(); })()""")
            await asyncio.sleep(0.4)
            dlg = await js("$('#modalBody').textContent")
            await js("$('#modalOk').click()")
            await asyncio.sleep(0.2)
            sent = await js("window.__sent.filter(o => o.type === 'instructions_save')")
            await js("onRpc({command:'instructions_save', data:{scope:'global'}})")
            await asyncio.sleep(0.6)
            back = await js("sheetPage")
            checks += [
                ("guardar avisa de que se aplica al reiniciar",
                 "restarting pi remote" in dlg),
                ("envia el fichero con su tipo",
                 sent and sent[0]["kind"] == "agents"
                 and sent[0]["body"] == "Reply in Spanish.\nNew rule."),
                ("tras guardar vuelve a la lista", back == "instructions"),
            ]
            # atras con cambios sin guardar pregunta
            await js("onRpc({command:'instructions_get', data:{scope:'global',"
                     " files:%s, also:[]}})" % json.dumps(FILES))
            await asyncio.sleep(0.3)
            await js("[...document.querySelectorAll('#sheetBody .pick')][1].click()")
            await asyncio.sleep(0.4)
            await js("""(() => { const t = document.querySelector('#sheetBody textarea');
              t.value = 'x'; t.dispatchEvent(new Event('input')); goBack(); })()""")
            await asyncio.sleep(0.3)
            guard = await js("[$('#modal').classList.contains('open'),"
                             " $('#modalTitle').textContent]")
            await js("closeModal()")
            checks.append(("atras con cambios pregunta si descartar",
                           guard[0] and guard[1] == "Discard changes?"))

            # proyecto: su card y la lista de lo que pi carga ademas
            await js("instrDraft = null; openInstr('project')")
            await asyncio.sleep(0.4)
            await js("""onRpc({command:'instructions_get', data:{scope:'project',
              files:[{kind:'context', name:'CLAUDE.md', path:'C:/w/app/CLAUDE.md',
                      exists:true, body:'x'}],
              also:[{name:'AGENTS.md', path:'C:/Users/me/.pi/agent/AGENTS.md',
                     global:true}]}})""")
            await asyncio.sleep(0.4)
            pr = await js("""(() => ({
              rows: [...document.querySelectorAll('#sheetBody .pick')]
                .map(b => b.textContent.trim()),
              heads: [...document.querySelectorAll('#sheetBody .shead')]
                .map(h => h.textContent),
              also: [...document.querySelectorAll('#sheetBody .extrow')].length}))()""")
            print("  proyecto:", pr)
            checks += [
                ("proyecto: el fichero que pi usa (CLAUDE.md), no un AGENTS.md",
                 len(pr["rows"]) == 1 and pr["rows"][0].startswith("CLAUDE.md")),
                ("y aparte, solo leer, lo que se carga ademas",
                 "Also loaded" in pr["heads"] and pr["also"] == 1),
            ]
            await js("closeModal(); menuSheet(); goPage('projset')")
            await asyncio.sleep(0.5)
            pcard = await js("""(() => { const b = [...document.querySelectorAll('#sheetBody .pick')]
              .find(x => x.textContent.trim() === 'Instructions');
              return b ? !b.disabled : null; })()""")
            checks.append(("card en project settings, activa aunque el "
                           "interruptor de ajustes este apagado", pcard is True))
    return checks


async def main():
    return backend() + await ui()

raise SystemExit(report(asyncio.run(main())))
