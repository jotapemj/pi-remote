"""El atras del navegador cierra capas en vez de salir de la pagina, y los
arreglos de UI que van con el: menu de tres puntos que no se sale por la
derecha, toggle de skill que se mueve al pulsarlo, y el velo de la hoja que ya
no cierra cuando el gesto solo TERMINA en el (seleccionar texto y soltar
fuera).

La guardia del historial es una sola entrada: cada atras la consume, se cierra
la capa mas alta y se rearma si queda algo abierto.
"""
import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from harness import Bridge, Page, report

TMP = Path(tempfile.gettempdir()) / "navback_probe_tmp"


def seed(td):
    g = Path(td) / "skills"
    (g / "alpha").mkdir(parents=True)
    (g / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: First\n---\n\nBody A", encoding="utf-8")
    (Path(td) / "extensions").mkdir()


async def ui():
    checks = []
    shutil.rmtree(TMP, ignore_errors=True)
    td = str(TMP); TMP.mkdir(parents=True)
    seed(td)
    with Bridge(extra={"PI_AGENT_DIR": td}):
        async with Page(port=9428) as p:
            js = p.js
            await p.go()
            await js("setLang('en')")

            # ---- atras dentro del menu: camina las paginas ----
            await js("$('#sheet').classList.add('open'); navArm();"
                     " paintSheet('root')")
            await asyncio.sleep(0.2)
            await js("goPage('premote')")
            await asyncio.sleep(0.45)
            deep = await js("sheetPage")
            await js("history.back()")
            await asyncio.sleep(0.5)
            back1 = await js("({page:sheetPage,"
                             " open:$('#sheet').classList.contains('open')})")
            await js("history.back()")
            await asyncio.sleep(0.5)
            back2 = await js("({page:sheetPage,"
                             " open:$('#sheet').classList.contains('open')})")
            checks += [
                ("el menu entra en una subpagina", deep == "premote"),
                ("atras vuelve a la pagina anterior, sin cerrar",
                 back1["page"] == "root" and back1["open"] is True),
                ("otro atras cierra la hoja", back2["open"] is False),
            ]

            # ---- atras cierra el rail ----
            await js("openRail()")
            await asyncio.sleep(0.4)
            was = await js("$('#rail').classList.contains('on')")
            await js("history.back()")
            await asyncio.sleep(0.5)
            now = await js("$('#rail').classList.contains('on')")
            checks.append(("atras cierra la barra lateral",
                           was is True and now is False))

            # ---- atras cierra el dialogo antes que nada ----
            await js("$('#sheet').classList.add('open'); navArm();"
                     " openModal('t','b',()=>{})")
            await asyncio.sleep(0.4)
            await js("history.back()")
            await asyncio.sleep(0.5)
            md = await js("({modal:$('#modal').classList.contains('open'),"
                          " sheet:$('#sheet').classList.contains('open')})")
            checks.append(("el dialogo se cierra antes que la hoja de debajo",
                           md["modal"] is False and md["sheet"] is True))
            await js("$('#sheet').classList.remove('open')")

            # ---- sin nada abierto, no se secuestra el atras ----
            idle = await js("(()=>{navArmed=false; return closeTopLayer();})()")
            checks.append(("sin capas abiertas no hay nada que cerrar",
                           idle is False))

            # ---- el velo no cierra si el gesto solo TERMINA en el ----
            await js("$('#sheet').classList.add('open'); paintSheet('root')")
            await asyncio.sleep(0.25)
            drag = await js("""(()=>{
              const sh=$('#sheet');
              const inner=sh.querySelector('.card');
              // down dentro de la card, up sobre el velo: el click salta en
              // #sheet, que es el ancestro comun de los dos
              inner.dispatchEvent(new PointerEvent('pointerdown',
                {bubbles:true}));
              sh.dispatchEvent(new MouseEvent('click', {bubbles:true}));
              return sh.classList.contains('open');})()""")
            tap = await js("""(()=>{
              const sh=$('#sheet');
              sh.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));
              sh.dispatchEvent(new MouseEvent('click',{bubbles:true}));
              return sh.classList.contains('open');})()""")
            checks += [
                ("soltar en el velo tras arrastrar dentro no cierra",
                 drag is True),
                ("pero tocar el velo si cierra", tap is False),
            ]

            # ---- el menu de tres puntos no se sale por la derecha ----
            await js("$('#sheet').classList.add('open')")
            await js("(async()=>{[...document.querySelectorAll('#sheetBody .pick')]"
                     ".find(b=>/pi agent/.test(b.textContent)).click();"
                     " await new Promise(r=>setTimeout(r,450));"
                     " [...document.querySelectorAll('#sheetBody .pick')]"
                     ".find(b=>/Global/.test(b.textContent)).click();"
                     " await new Promise(r=>setTimeout(r,450));"
                     " [...document.querySelectorAll('#sheetBody .pick')]"
                     ".find(b=>/Resources/.test(b.textContent)).click();"
                     " await new Promise(r=>setTimeout(r,600));})()")
            await asyncio.sleep(0.5)
            pop = await js("""(()=>{
              const d=document.querySelector('#sheetBody .skrow .dotsb');
              if(!d) return {err:'sin filas'};
              d.click();
              const p=document.querySelector('.ctxpop');
              if(!p) return {err:'sin popup'};
              const r=p.getBoundingClientRect();
              return {left:r.left, right:r.right, w:innerWidth,
                rows:[...p.querySelectorAll('.ctxrow')].map(x=>x.textContent)};
              })()""")
            checks += [
                ("los tres puntos abren el menu",
                 not pop.get("err") and pop["rows"] == ["Delete"]),
                ("y el menu cabe entero en la pantalla",
                 not pop.get("err")
                 and pop["left"] >= 0 and pop["right"] <= pop["w"] + 0.5),
            ]

            # ---- el borrado avisa de lo que hace ----
            await js("document.querySelector('.ctxpop .ctxrow').click()")
            await asyncio.sleep(0.35)
            dlg = await js("""({open:$('#modal').classList.contains('open'),
              title:($('#modalTitle')||{}).textContent||'',
              body:($('#modalBody')||{}).textContent||''})""")
            checks.append(
                ("el dialogo dice que borra la carpeta y es irreversible",
                 dlg["open"] and "alpha" in dlg["title"]
                 and "folder" in dlg["body"] and "undone" in dlg["body"]))
            await js("closeModal()")
            await asyncio.sleep(0.3)

            # ---- el toggle de la skill se mueve al pulsarlo ----
            tog = await js("""(()=>{
              const sw=document.querySelector('#sheetBody .skrow .sw');
              if(!sw) return {err:'sin toggle'};
              const before=sw.getAttribute('aria-checked');
              sw.click();
              return {before, after:sw.getAttribute('aria-checked'),
                trans:getComputedStyle(sw.querySelector('.knob'))
                        .transitionDuration};})()""")
            checks.append(
                ("el toggle cambia en el acto, sin esperar al puente",
                 not tog.get("err") and tog["before"] != tog["after"]
                 and tog["trans"].startswith("0.2")))

            # ---- los numeros van todos en la misma fuente ----
            await js("onRpc({command:'compaction_get', data:{global:{},"
                     "project:{}, window:150000, maxTokens:16384,"
                     "defaults:{enabled:true,reserveTokens:16384,"
                     "keepRecentTokens:20000}}})")
            await js("paintSheet('compaction')")
            await asyncio.sleep(0.3)
            fonts = await js("""(()=>{
              const n=document.querySelector('.cnum');
              const mono=getComputedStyle(document.documentElement)
                .getPropertyValue('--mono').trim();
              return n ? {f:getComputedStyle(n).fontFamily,
                          tab:getComputedStyle(n).fontVariantNumeric,
                          mono} : {};})()""")
            checks.append(("los numeros son monoespaciados y tabulares",
                           bool(fonts.get("f"))
                           and fonts["f"].split(",")[0].replace('"', '')
                           in fonts["mono"]
                           and "tabular" in fonts["tab"]))
    return checks


raise SystemExit(report(asyncio.run(ui())))
