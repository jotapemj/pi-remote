"""Recursos: skills y extensiones. Pi es el dueño de los ficheros; el puente
los lista, alterna .ignore (el loader de pi lo respeta), escribe SKILL.md y
borra carpetas. Las extensiones son solo ver."""
import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from harness import Bridge, Page, report

TMP = Path(tempfile.gettempdir()) / "skills_probe_tmp"


def seed(td):
    """Un agent dir con dos skills globales (una con fichero extra) y una
    extension, mas un proyecto con su skill propia."""
    g = Path(td) / "skills"
    (g / "alpha").mkdir(parents=True)
    (g / "alpha" / "SKILL.md").write_text(
        "---\nname: \"alpha\"\ndescription: \"First skill\"\n---\n\nBody A",
        encoding="utf-8")
    (g / "beta").mkdir()
    (g / "beta" / "SKILL.md").write_text(
        "---\nname: beta\ndescription: Second\n---\n\nBody B",
        encoding="utf-8")
    (g / "beta" / "tool.py").write_text("print('x')", encoding="utf-8")
    ex = Path(td) / "extensions"
    ex.mkdir()
    (ex / "guard.ts").write_text("export {}", encoding="utf-8")
    (ex / "notes.txt").write_text("no es extension", encoding="utf-8")
    # paquete npm con manifest 'pi': una extension y una skill
    pk = Path(td) / "npm" / "node_modules" / "fakepkg"
    (pk / "skills" / "hello").mkdir(parents=True)
    (pk / "package.json").write_text(
        json.dumps({"name": "fakepkg",
                    "pi": {"extensions": ["./index.ts"],
                           "skills": ["./skills/hello/SKILL.md"]}}),
        encoding="utf-8")
    (pk / "index.ts").write_text("export {}", encoding="utf-8")
    (pk / "skills" / "hello" / "SKILL.md").write_text(
        "---\nname: hello\ndescription: From a package\n---\n\nBody H",
        encoding="utf-8")
    (Path(td) / "settings.json").write_text(
        json.dumps({"packages": ["npm:fakepkg"]}), encoding="utf-8")
    proj = Path(td) / "proj"
    (proj / ".pi" / "skills" / "gamma").mkdir(parents=True)
    (proj / ".pi" / "skills" / "gamma" / "SKILL.md").write_text(
        "---\nname: gamma\ndescription: Project skill\n---\n\nBody G",
        encoding="utf-8")
    return proj


def backend():
    import pi_web_bridge as B
    checks = []
    shutil.rmtree(TMP, ignore_errors=True)
    td = str(TMP); TMP.mkdir(parents=True)
    proj = seed(td)
    B.AGENT_DIR = Path(td)
    try:
        # lista global: nombre, descripcion, extra, enabled
        ls = B.skills_list("global", "/x")
        by = {s["dir"]: s for s in ls if s["dir"]}
        checks += [
            ("lista las dos skills globales", set(by) == {"alpha", "beta"}),
            ("el frontmatter se parsea",
             by["alpha"]["name"] == "alpha"
             and by["alpha"]["description"] == "First skill"),
            ("el body viaja con la entrada", by["alpha"]["body"].startswith("Body A")),
            ("los ficheros extra se cuentan", by["beta"]["extra"] == 1),
            ("nacidas activas", all(s["enabled"] for s in ls)),
        ]
        # skill de paquete: sale por el manifest, solo ver
        ph = [s for s in ls if s.get("source") == "package"]
        checks += [
            ("la skill del paquete sale por el manifest",
             len(ph) == 1 and ph[0]["name"] == "hello"
             and ph[0]["pkg"] == "fakepkg"),
            ("la de paquete no es operable (dir None)",
             ph and ph[0]["dir"] is None and ph[0]["enabled"] is True),
        ]
        # scope de proyecto: solo la suya
        pl = B.skills_list("project", str(proj))
        checks.append(("el proyecto lista solo gamma",
                       [s["dir"] for s in pl] == ["gamma"]))
        # toggle: escribe .ignore y lo quita al reactivar
        err = B.skill_toggle("global", "/x", "beta", False)
        ig = Path(td) / "skills" / ".ignore"
        checks += [
            ("toggle off sin error", err is None),
            (".ignore escrito en la raiz de skills",
             ig.exists() and "beta" in ig.read_text(encoding="utf-8")),
            ("la lista la marca desactivada",
             not {s["dir"]: s for s in B.skills_list("global", "/x")}["beta"]["enabled"]),
        ]
        err = B.skill_toggle("global", "/x", "beta", True)
        checks.append(("toggle on borra la linea", err is None
                       and "beta" not in ig.read_text(encoding="utf-8")))
        # conservar contenido ajeno al .ignore
        ig.write_text("# comentario\nalpha\n", encoding="utf-8")
        B.skill_toggle("global", "/x", "beta", False)
        txt = ig.read_text(encoding="utf-8")
        checks.append(("el .ignore ajeno se conserva",
                       "# comentario" in txt and "alpha" in txt
                       and "beta" in txt))
        # crear skill nueva
        err = B.skill_save("global", "/x", "delta", "New one", "Body D")
        d = Path(td) / "skills" / "delta" / "SKILL.md"
        checks += [
            ("skill_save crea la carpeta", err is None and d.is_file()),
            ("el frontmatter redondea",
             d.read_text(encoding="utf-8").startswith("---\nname:")),
        ]
        # renombrar: oldDir -> name, el contenido se mantiene
        err = B.skill_save("global", "/x", "delta2", "New one", "Body D",
                           old_dir="delta")
        checks += [
            ("renombrar mueve la carpeta",
             err is None and not (Path(td) / "skills" / "delta").exists()
             and (Path(td) / "skills" / "delta2" / "SKILL.md").is_file()),
        ]
        # colision y nombres malos
        checks += [
            ("colision de nombre da error",
             "already in use" in B.skill_save(
                 "global", "/x", "alpha", "x", "y", old_dir="delta2")),
            ("nombre con separador da error",
             "bad name" in B.skill_save("global", "/x", "a/b", "x", "y")),
            ("nombre con .. da error",
             "bad name" in B.skill_save("global", "/x", "..", "x", "y")),
            ("descripcion larga da error",
             "too long" in B.skill_save(
                 "global", "/x", "eps", "x" * 1025, "y")),
        ]
        # borrar
        err = B.skill_delete("global", "/x", "delta2")
        checks += [
            ("skill_delete borra la carpeta",
             err is None and not (Path(td) / "skills" / "delta2").exists()),
            ("borrar lo que no existe da error",
             "not found" in B.skill_delete("global", "/x", "delta2")),
        ]
        # extensiones: solo .ts/.js, sin el txt, mas la del paquete
        ex = B.extensions_list("global", "/x")
        byname = {e["name"]: e for e in ex}
        checks += [
            ("extensiones lista guard.ts y la del paquete",
             set(byname) == {"guard", "index"}),
            ("la del paquete lleva su origen",
             byname["index"].get("source") == "package"
             and byname["index"].get("pkg") == "fakepkg"),
        ]
        pex = B.extensions_list("project", str(proj))
        checks.append(("el proyecto sin packages: vacio", pex == []))
    finally:
        del B.AGENT_DIR
    return checks


async def ui():
    checks = []
    shutil.rmtree(TMP, ignore_errors=True)
    td = str(TMP); TMP.mkdir(parents=True)
    seed(td)
    with Bridge(extra={"PI_AGENT_DIR": td}):
        async with Page(port=9390) as p:
            js = p.js
            await p.go()
            await js("setLang('en')")
            # el modelo llega inyectado, como en model_probe (el fake_pi del
            # harness no alimenta get_available_models al puente de verdad)
            await js("onRpc({command:'get_available_models', data:{models:["
                     "{id:'qwen3-8b',name:'Qwen3 8B',provider:'local',"
                     "contextWindow:32768}]}})")

            # ---- navegacion: la fila Resources en ajustes globales ----
            await js("paintSheet('root')")
            await asyncio.sleep(0.4)
            await js("(async()=>{[...document.querySelectorAll('#sheetBody .pick')]"
                     ".find(b=>/pi agent/.test(b.textContent)).click();"
                     " await new Promise(r=>setTimeout(r,400));})()")
            await js("(async()=>{[...document.querySelectorAll('#sheetBody .pick')]"
                     ".find(b=>/Global settings/.test(b.textContent)).click();"
                     " await new Promise(r=>setTimeout(r,400));})()")
            modelrows = await js("""[...document.querySelectorAll('#sheetBody .pick')]
              .map(b=>b.querySelector('.txt span').textContent)""")
            checks.append(("la pagina global lista 'Resources'",
                           "Resources" in modelrows))

            # ---- pagina de recursos: filas y extensiones ----
            await js("(async()=>{[...document.querySelectorAll('#sheetBody .pick')]"
                     ".find(b=>/Resources/.test(b.textContent)).click();"
                     " await new Promise(r=>setTimeout(r,500));})()")
            rows = await js("""(()=>{
              const rs=[...document.querySelectorAll('#sheetBody .skrow:not(.extrow)')];
              return {n:rs.length,
                names:rs.map(r=>r.querySelector('.stxt span').textContent),
                pkg:rs.filter(r=>!r.querySelector('.sw')).length,
                ext:[...document.querySelectorAll('#sheetBody .extrow')]
                      .map(r=>r.querySelector('.stxt span').textContent)};})()""")
            checks += [
                ("las dos skills globales salen en filas",
                 rows["n"] == 3 and set(rows["names"]) == {"alpha", "beta", "hello"}),
                ("la del paquete sale sin toggle", rows["pkg"] == 1),
                ("las dos extensions salen en su seccion",
                 sorted(rows["ext"]) == ["guard", "index"]),
            ]

            # ---- cabecera fija + secciones sticky ----
            lay = await js("""(()=>{
              const cs = getComputedStyle($('#sheetBody'));
              const cc = getComputedStyle(document.querySelector('#sheet .card'));
              return {body:cs.overflowY, flex:cs.flexGrow,
                      card:cc.overflowY, pos:getComputedStyle(
                        document.querySelector('#sheetBody .sec > .shead')).position};})()""")
            checks += [
                ("el cuerpo scrollea, no la card",
                 lay["body"] == "auto" and lay["flex"] == "1"
                 and lay["card"] in ("hidden", "clip")),
                ("las cabeceras de seccion son sticky",
                 lay["pos"] == "sticky"),
            ]
            # forzar desborde: la card entera cabe, el cuerpo no
            await js("""(()=>{const b=$('#sheetBody');
              b.style.height='150px'; b.style.flex='none';})()""")
            # punto donde la cabecera de extensions empieza a fijarse:
            # 40 px dentro de su seccion, con la seccion todavia en vista
            await js("""(()=>{
              const b = $('#sheetBody');
              const s2 = document.querySelector('.extsec');
              const nat = s2.getBoundingClientRect().top
                - b.getBoundingClientRect().top + b.scrollTop;
              b.scrollTop = nat + 40;})()""")
            await asyncio.sleep(0.3)
            st = await js("""(()=>{
              const b = $('#sheetBody');
              const bt = b.getBoundingClientRect().top;
              const tops = [...b.querySelectorAll('.sec > .shead')]
                .map(h => Math.round(h.getBoundingClientRect().top));
              return {bt, tops, st: b.scrollTop};})()""")
            checks += [
                ("el cuerpo se scrolleo", st["st"] > 10),
                ("'extensions' queda fija arriba en su seccion",
                 st["tops"][-1] >= st["bt"] - 2
                 and st["tops"][-1] <= st["bt"] + 16),
                ("'skills' se fue con el scroll",
                 st["tops"][0] < st["bt"]),
            ]
            await js("""(()=>{const b=$('#sheetBody');
              b.style.height=''; b.style.flex=''; b.scrollTop=0;})()""")

            # ---- toggle desde la fila ----
            await js("""(()=>{[...document.querySelectorAll('#sheetBody .skrow')]
              .find(r=>/beta/.test(r.textContent)).querySelector('.sw').click();})()""")
            await asyncio.sleep(0.4)
            ig = Path(td) / "skills" / ".ignore"
            checks.append(("el toggle de la fila escribe .ignore",
                           ig.exists() and "beta" in ig.read_text(encoding="utf-8")))
            off = await js("""[...document.querySelectorAll('#sheetBody .skrow')]
              .find(r=>/beta/.test(r.textContent)).querySelector('.sw')
              .getAttribute('aria-checked')""")
            checks.append(("la fila se repinta desactivada", off == "false"))

            # ---- compositor: nueva skill completa ----
            await js("""[...document.querySelectorAll('#sheetBody .pick')]
              .find(b=>/New skill/.test(b.textContent)).click()""")
            await asyncio.sleep(0.4)
            st = await js("({t:$('#sheetTitle').textContent,"
                          "ok:$('#sheetOk').hidden})")
            checks += [
                ("el compositor abre en 'New skill'", st["t"] == "New skill"),
                ("sin nombre el check esta oculto", st["ok"] is True),
            ]
            await js("""(()=>{
              const ins=[...document.querySelectorAll('#sheetBody .mfield input')];
              ins[0].value='zeta'; ins[0].dispatchEvent(new Event('input'));
              ins[1].value='From the UI'; ins[1].dispatchEvent(new Event('input'));
              const ta=document.querySelector('#sheetBody .mfield.ta textarea');
              ta.value='UI body'; ta.dispatchEvent(new Event('input'));})()""")
            okvis = await js("!$('#sheetOk').hidden")
            checks.append(("con nombre valido el check aparece", okvis is True))
            await js("$('#sheetOk').click()")
            await asyncio.sleep(0.3)
            md = await js("({open:$('#modal').classList.contains('open'),"
                          "t:$('#modalTitle').textContent})")
            checks.append(("el guardado pide confirmacion",
                           md["open"] and md["t"] == "Confirm changes?"))
            await js("$('#modalOk').click()")
            await asyncio.sleep(0.5)
            z = Path(td) / "skills" / "zeta" / "SKILL.md"
            checks += [
                ("la skill nueva queda en disco", z.is_file()),
                ("el body viajo al fichero",
                 z.read_text(encoding="utf-8").endswith("UI body")),
                ("volvio a la lista de recursos",
                 (await js("sheetPage")) == "resglobal"),
            ]

            # ---- borrar por los tres puntos ----
            await js("""(()=>{[...document.querySelectorAll('#sheetBody .skrow')]
              .find(r=>/zeta/.test(r.textContent)).querySelector('.dotsb')
              .click();})()""")
            await asyncio.sleep(0.3)
            pop = await js("""(()=>{const p=document.querySelector('.ctxpop');
              return p ? [...p.querySelectorAll('.ctxrow')]
                       .map(b=>b.textContent) : [];})()""")
            checks.append(("los tres puntos ofrecen el borrado",
                           any("Permanently delete" in x for x in pop)))
            await js("document.querySelector('.ctxpop .ctxrow').click()")
            await asyncio.sleep(0.3)
            await js("$('#modalOk').click()")
            await asyncio.sleep(0.5)
            checks += [
                ("el borrado quita la carpeta",
                 not (Path(td) / "skills" / "zeta").exists()),
                ("la fila desaparecio de la lista",
                 (await js("""[...document.querySelectorAll('#sheetBody .skrow')]
                   .some(r=>/zeta/.test(r.textContent))""")) is False),
            ]
    return checks


async def main():
    return backend() + await ui()


raise SystemExit(report(asyncio.run(main())))
