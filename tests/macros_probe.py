"""Macros: las plantillas de prompt de pi, lanzadas desde el movil.

Ficheros .md en AGENT_DIR/prompts y <cwd>/.pi/prompts. pi los convierte en
comandos en su TUI, pero en modo RPC NO los expande: su handler de `prompt`
no pasa expandPromptTemplates (por defecto false). Asi que la expansion la
hace el PUENTE y a pi le llega un prompt normal, ya resuelto.
"""
import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from harness import Bridge, Page, report

TMP = Path(tempfile.gettempdir()) / "macros_probe_tmp"


def seed(td):
    """Dos macros globales (una con argumentos) y una del proyecto que
    repite nombre, para comprobar quien gana."""
    g = Path(td) / "prompts"
    g.mkdir(parents=True)
    (g / "review.md").write_text(
        "---\ndescription: Review staged changes\n"
        "argument-hint: <path>\n---\n\nReview $1 and report back.",
        encoding="utf-8")
    (g / "compare.md").write_text(
        "---\ndescription: Compare two files\n"
        "argument-hint: <antes> <despues>\n---\n\n"
        "Compara $1 con $2 y dime las diferencias.",
        encoding="utf-8")
    (g / "standup.md").write_text(
        "---\ndescription: Daily summary\n---\n\nSummarise what changed today.",
        encoding="utf-8")
    (g / "notes.txt").write_text("no es un macro", encoding="utf-8")
    proj = Path(td) / "proj"
    (proj / ".pi" / "prompts").mkdir(parents=True)
    (proj / ".pi" / "prompts" / "review.md").write_text(
        "---\ndescription: Project review\n---\n\nProject-specific review.",
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
        g = B.prompts_list("global", "")
        by = {x["name"]: x for x in g}
        checks += [
            ("lista los .md de prompts, y solo esos",
             sorted(by) == ["compare", "review", "standup"]),
            ("el nombre es el del fichero",
             by["review"]["name"] == "review"),
            ("el frontmatter da descripcion y pista de argumentos",
             by["review"]["description"] == "Review staged changes"
             and by["review"]["argumentHint"] == "<path>"),
            ("el cuerpo viaja sin el frontmatter",
             by["review"]["body"].startswith("Review $1")),
            ("se marca cual pide argumentos",
             by["review"]["needsArgs"] is True
             and by["standup"]["needsArgs"] is False),
        ]
        # un "$" cualquiera no es un hueco: con la deteccion burda, un
        # cuerpo que hablara de $HOME pedia argumentos que nadie sustituia
        v = B.PROMPT_VAR.search
        checks += [
            ("los marcadores se reconocen",
             all(v(x) for x in ("Lee $1", "Resume $@", "Todo: $ARGUMENTS"))),
            ("y un dolar cualquiera no cuenta como hueco",
             not any(v(x) for x in ("Usa $HOME/bin", "cuesta $ y pico",
                                    "sin nada"))),
        ]

        checks += [
            ("se sabe que huecos usa cada plantilla",
             by["review"]["slots"] == {"nums": [1], "all": False}
             and by["compare"]["slots"] == {"nums": [1, 2], "all": False}
             and by["standup"]["slots"] == {"nums": [], "all": False}),
            ("una plantilla puede saltarse un numero",
             B.prompt_slots("solo $2") == {"nums": [2], "all": False}),
            ("y $@ se marca aparte",
             B.prompt_slots("todo $@") == {"nums": [], "all": True}),
        ]

        pl = B.prompts_list("project", str(proj))
        checks.append(("el proyecto trae las suyas",
                       [x["name"] for x in pl] == ["review"]
                       and pl[0]["description"] == "Project review"))
        checks.append(("sin carpeta prompts, lista vacia",
                       B.prompts_list("project", str(Path(td))) == []))

        # --- la expansion, que es lo que pi NO hace en RPC ---
        e = B.expand_prompt
        checks += [
            ("$1 toma el primer argumento",
             e("Review $1 now", ["auth.py"]) == "Review auth.py now"),
            ("$@ y $ARGUMENTS toman todos",
             e("A $@ B", ["x", "y"]) == "A x y B"
             and e("$ARGUMENTS", ["x", "y"]) == "x y"),
            ("un marcador sin argumento queda vacio",
             e("$1 y $2", ["uno"]) == "uno y "),
            ("sin marcadores el texto no se toca",
             e("texto plano", ["x"]) == "texto plano"),
            # el numero se lee entero: con $1 sustituido primero, "$12"
            # se convertiria en "<arg1>2"
            ("los marcadores de dos cifras no se parten",
             e("$12", ["a"] * 11 + ["doce"]) == "doce"),
        ]
        a = B.parse_prompt_args
        checks += [
            ("los argumentos se trocean por espacios",
             a("uno dos tres") == ["uno", "dos", "tres"]),
            ("y las comillas agrupan",
             a('foo "dos palabras" bar') == ["foo", "dos palabras", "bar"]),
            ("sin argumentos, lista vacia", a("") == []),
            # "" es un hueco vacio a proposito, no una ausencia: si se
            # descarta, todo lo que viene detras se corre una posicion
            ('un "" cuenta como argumento vacio',
             a('a "" b') == ["a", "", "b"]),
        ]
        # una plantilla puede saltarse un numero: con los valores en su
        # posicion, $3 recibe el suyo. Uniendolos en una linea, el segundo
        # caia en $2 y $3 se quedaba vacio
        checks.append(
            ("un hueco saltado recibe su valor, no el del vecino",
             e("Compara $1 con $3", ["a", "", "b"]) == "Compara a con b"))
    finally:
        del B.AGENT_DIR
    return checks


async def ui():
    checks = []
    shutil.rmtree(TMP, ignore_errors=True)
    td = str(TMP); TMP.mkdir(parents=True)
    seed(td)
    with Bridge(extra={"PI_AGENT_DIR": td}):
        async with Page(port=9436) as p:
            js = p.js
            await p.go()
            await js("setLang('en')")

            # ---- se abren desde el compositor, donde estas al necesitarlos ----
            entry = await js("""(()=>{
              const b=[...document.querySelectorAll('#plusMenu .pmi')]
                .find(x=>x.dataset.act==='macros');
              return b ? b.textContent.trim() : '';})()""")
            checks.append(("el menu del + ofrece los macros", entry == "Macros"))

            # iconos: code_xml para macros, terminal_2 para comandos
            ics = await js("""(()=>{
              const g=a=>{const b=[...document.querySelectorAll('#plusMenu .pmi')]
                .find(x=>x.dataset.act===a); return b?b.querySelector('[data-ic]').dataset.ic:'';};
              return {macros:g('macros'), commands:g('commands')};})()""")
            checks += [
                ("el icono de macros es code xml",
                 ics["macros"] == "codeXml"),
                ("el icono de comandos es terminal 2",
                 ics["commands"] == "terminal2"),
            ]

            await js("openMacros()")
            await asyncio.sleep(0.8)
            # las filas de macro llevan /nombre; la primera es crear
            rows = await js("""(()=>{
              const r=[...document.querySelectorAll('#sheetBody .pick')]
                .filter(x=>/^\//.test(x.textContent.trim()));
              return {n:r.length, txt:r.map(x=>x.textContent),
                page:sheetPage};})()""")
            checks += [
                ("la hoja lista los macros con su barra",
                 rows["page"] == "macros" and rows["n"] == 3
                 and any("/review" in x for x in rows["txt"])
                 and any("/standup" in x for x in rows["txt"])),
                ("y ensena para que sirve cada uno",
                 any("Review staged changes" in x for x in rows["txt"])),
            ]

            # ---- uno sin argumentos se lanza directo ----
            await js("""[...document.querySelectorAll('#sheetBody .pick')]
              .find(x=>/^\/standup/.test(x.textContent.trim())).click()""")
            await asyncio.sleep(0.6)
            sent = await js("""({open:$('#sheet').classList.contains('open'),
              modal:$('#modal').classList.contains('open')})""")
            checks.append(("un macro sin argumentos se lanza sin preguntar",
                           sent["open"] is False and sent["modal"] is False))

            # feedback: aparece un chip de usuario con el nombre del macro
            chip = await js("""(()=>{
              const c=document.querySelector('#feed .macrochip');
              return c ? {txt:c.textContent.trim(),
                          icon:!!c.querySelector('svg path')} : null;})()""")
            checks += [
                ("el macro deja un chip de usuario en el feed",
                 isinstance(chip, dict) and "/standup" in chip["txt"]
                 and chip["icon"]),
            ]

            # tocarlo muestra el prompt resuelto, solo informativo
            dlg = await js("""(()=>{
              document.querySelector('#feed .macrochip').click();
              return {open:$('#modal').classList.contains('open'),
                      title:$('#modalTitle').textContent,
                      body:$('#modalBody').textContent,
                      noHidden:$('#modalNo').hidden};})()""")
            checks += [
                ("el chip abre un dialogo informativo",
                 dlg["open"] is True and dlg["noHidden"] is True),
                ("titulo: el nombre del macro",
                 dlg["title"] == "/standup"),
                ("cuerpo: el texto con los $ resueltos",
                 "Summarise what changed today" in dlg["body"]),
            ]
            await js("closeModal()")

            # ---- sin macros, lo que hay es la accion de crear uno ----
            empty = await js("""(()=>{
              macros = []; paintSheet('macros');
              const b=[...document.querySelectorAll('#sheetBody .pick')];
              return {n:b.length, txt:b.map(x=>x.textContent.trim()),
                prosa:$('#sheetBody').textContent};})()""")
            checks += [
                ("sin macros, un boton de crear y nada mas",
                 empty["n"] == 1 and empty["txt"] == ["New macro"]),
                ("sin parrafos explicando donde va el fichero",
                 "$@" not in empty["prosa"]
                 and "prompts/" not in empty["prosa"]),
            ]

            # ---- crear: con proyecto abierto, se elige donde vive ----
            scopes = await js("""(()=>{
              state.cwd = 'C:/proj';
              newMacro(document.querySelector('#sheetBody .pick'));
              const p=document.querySelector('.ctxpop');
              return p ? [...p.querySelectorAll('.ctxrow')]
                .map(x=>x.textContent.trim()) : [];})()""")
            checks.append(("con proyecto abierto pregunta global o proyecto",
                           scopes == ["Global", "Project"]))
            await js("""[...document.querySelectorAll('.ctxpop .ctxrow')]
              .find(x=>/Project/.test(x.textContent)).click()""")
            await asyncio.sleep(0.5)
            form = await js("""(()=>{
              const f=[...document.querySelectorAll('#sheetBody .mfield label')]
                .map(x=>x.textContent);
              return {page:sheetPage, labels:f,
                sub:(document.querySelector('#sheetBody .shead')||{}).textContent,
                ok:$('#sheetOk').hidden};})()""")
            checks += [
                ("el compositor pide nombre, descripcion, pista y cuerpo",
                 form["page"] == "macroedit"
                 and form["labels"] == ["Name", "Description",
                                        "Argument hint", "Instructions"]),
                ("recuerda el ambito elegido", form["sub"] == "Project"),
                ("vacio no deja guardar", form["ok"] is True),
            ]
            # sin proyecto abierto no hay nada que preguntar
            direct = await js("""(()=>{
              state.cwd = ''; macroDraft = null;
              sheetStack=[]; paintSheet('macros');
              newMacro(document.querySelector('#sheetBody .pick'));
              return {pop:!!document.querySelector('.ctxpop'),
                scope:macroDraft ? macroDraft.scope : null};})()""")
            checks.append(("sin proyecto va directo a global",
                           direct["pop"] is False
                           and direct["scope"] == "global"))

            # ---- uno con argumentos los pide primero ----
            # goPage anima: sin esperar, su paintSheet pendiente pisa al
            # siguiente y la hoja se queda en el compositor
            await asyncio.sleep(0.45)
            await js("openMacros()")
            await asyncio.sleep(0.6)
            await js("""[...document.querySelectorAll('#sheetBody .pick')]
              .find(x=>/^\/review/.test(x.textContent.trim())).click()""")
            await asyncio.sleep(0.4)
            ask = await js("""({open:$('#modal').classList.contains('open'),
              title:$('#modalTitle').textContent,
              field:!!$('#modalInput'),
              lbl:(document.querySelector('#modalBody label')||{}).textContent||''})""")
            checks.append(
                ("uno con marcadores pide los argumentos, con su pista",
                 ask["open"] and ask["title"] == "/review"
                 and ask["field"] and ask["lbl"] == "<path>"))
            await js("$('#modalInput').value='auth.py'; $('#modalOk').click()")
            await asyncio.sleep(0.8)

            # ---- varios huecos: un campo por hueco, con su nombre ----
            await js("openMacros()")
            await asyncio.sleep(0.7)
            await js("""[...document.querySelectorAll('#sheetBody .pick')]
              .find(x=>/^\\/compare/.test(x.textContent.trim())).click()""")
            await asyncio.sleep(0.4)
            multi = await js("""(()=>{
              const w=document.querySelector('#modalBody .mfields');
              const ins=[...document.querySelectorAll('#modalBody input')];
              const lbl=[...document.querySelectorAll('#modalBody label')]
                .map(x=>x.textContent);
              const cs=w?getComputedStyle(w):null;
              return {n:ins.length, lbl,
                scroll:cs?cs.overflowY:'', mask:cs?cs.maskImage:''};})()""")
            checks += [
                ("dos huecos dan dos campos", multi["n"] == 2),
                # pi no admite marcadores con nombre: los nombres salen del
                # argument-hint, que es texto libre y es donde ya se ponen
                ("con el nombre del hint, no un mar de dolares",
                 multi["lbl"] == ["antes", "despues"]),
                ("la lista scrollea y se funde por los bordes",
                 multi["scroll"] == "auto" and "gradient" in multi["mask"]),
            ]
            checks.append(
                ("los dos campos conservan lo escrito",
                 (await js("""(()=>{
                   const ins=[...document.querySelectorAll('#modalBody input')];
                   ins[0].value='antes.py'; ins[1].value='dos palabras';
                   return ins.map(i=>i.value);})()"""))
                 == ["antes.py", "dos palabras"]))
            await js("$('#modalOk').click()")
            await asyncio.sleep(0.6)

            # los valores viajan en su POSICION, no unidos en una linea:
            # asi una plantilla que salte un numero recibe cada uno en su sitio
            # send es const: se envuelve ws.send, que es lo que acaba llamando
            argv = await js("""(()=>{
              macros=[{name:'skip', description:'', argumentHint:'<a> <b>',
                       needsArgs:true, scope:'global',
                       slots:{nums:[1,3], all:false}}];
              sheetStack=[]; paintSheet('macros');
              [...document.querySelectorAll('#sheetBody .pick')]
                .find(y=>/^\\/skip/.test(y.textContent.trim())).click();
              const ins=[...document.querySelectorAll('#modalBody input')];
              ins[0].value='uno'; ins[1].value='tres';
              const orig = ws.send.bind(ws);
              let sent = null;
              ws.send = s => { const m = JSON.parse(s);
                               if(m.type === 'prompt_run') sent = m;
                               orig(s); };
              $('#modalOk').click();
              ws.send = orig;
              return sent;})()""")
            checks.append(
                ("los valores viajan en su hueco, no unidos en una linea",
                 isinstance(argv, dict)
                 and argv.get("argv") == ["uno", "", "tres"]
                 and "args" not in argv))

            # sin hint, los campos se rotulan con su numero
            names = await js("""(()=>{
              macros=[{name:'x', description:'', argumentHint:'',
                       needsArgs:true, scope:'global',
                       slots:{nums:[1,2,3], all:false}}];
              paintSheet('macros');
              [...document.querySelectorAll('#sheetBody .pick')]
                .find(y=>/^\\/x/.test(y.textContent.trim())).click();
              return [...document.querySelectorAll('#modalBody label')]
                .map(y=>y.textContent);})()""")
            checks.append(("sin pista, cada campo lleva su numero",
                           names == ["$1", "$2", "$3"]))
            await js("closeModal()")

            # ---- atras: los macros se abren desde el compositor, no del
            # menu, asi que volver es volver AL CHAT, no caer en ajustes ----
            await js("openMacros()")
            await asyncio.sleep(0.7)
            back1 = await js("""(()=>{
              $('#sheetBack').click();
              return {open:$('#sheet').classList.contains('open'),
                page:sheetPage};})()""")
            checks.append(("atras desde los macros cierra la hoja",
                           back1["open"] is False))

            # pero dentro del compositor de macros, atras sube un nivel
            await js("openMacros()")
            await asyncio.sleep(0.7)
            await js("""[...document.querySelectorAll('#sheetBody .pick')]
              .find(x=>/New macro/.test(x.textContent)).click()""")
            await asyncio.sleep(0.5)
            back2 = await js("""(()=>{
              const was = sheetPage;
              $('#sheetBack').click();
              return {was, open:$('#sheet').classList.contains('open')};})()""")
            await asyncio.sleep(0.5)
            back2b = await js("sheetPage")
            checks.append(("desde el compositor vuelve a la lista, sin cerrar",
                           back2["was"] == "macroedit"
                           and back2["open"] is True
                           and back2b == "macros"))

            # y el menu de siempre no cambia: sus subpaginas vuelven a la raiz
            await js("menuSheet(); goPage('premote')")
            await asyncio.sleep(0.5)
            await js("$('#sheetBack').click()")
            await asyncio.sleep(0.5)
            menu = await js("""({page:sheetPage,
              open:$('#sheet').classList.contains('open')})""")
            checks.append(("el menu sigue volviendo a su raiz, sin cerrarse",
                           menu["page"] == "root" and menu["open"] is True))
    return checks


async def main():
    return backend() + await ui()


raise SystemExit(report(asyncio.run(main())))
