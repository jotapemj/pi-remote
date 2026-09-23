"""Lote de UI: rail fino (cruce de iconos con fundido, rotulos), menu
contextual junto al raton, borrado de modelo, nivel de razonamiento por
defecto y el teclado que se llevaba la cabecera.

El nivel por defecto vive en el settings GLOBAL de pi
(`defaultThinkingLevel`, lo que lee getDefaultThinkingLevel).
"""
import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from harness import Bridge, Page, report

TMP = Path(tempfile.gettempdir()) / "railui_probe_tmp"


def seed(td):
    (Path(td) / "models.json").write_text(json.dumps({"providers": {
        "local": {"baseUrl": "http://x/v1", "models": [
            {"id": "m-a", "name": "Model A", "contextWindow": 32768,
             "maxTokens": 4096},
            {"id": "m-b", "name": "Model B", "contextWindow": 16384,
             "maxTokens": 2048}]}}}), encoding="utf-8")
    (Path(td) / "settings.json").write_text(
        json.dumps({"theme": "dark"}), encoding="utf-8")


def backend():
    import pi_web_bridge as B
    checks = []
    shutil.rmtree(TMP, ignore_errors=True)
    td = str(TMP); TMP.mkdir(parents=True)
    seed(td)
    B.AGENT_DIR = Path(td)
    old = B.os.environ.pop("PI_MODELS_JSON", None)
    try:
        checks.append(("borrar un modelo que no existe da error",
                       B.model_delete("local", "nope") is not None))
        err = B.model_delete("local", "m-b")
        d = json.loads((Path(td) / "models.json").read_text(encoding="utf-8"))
        ids = [m["id"] for m in d["providers"]["local"]["models"]]
        checks += [
            ("borrar un modelo no da error", err is None),
            ("el modelo desaparece de models.json", ids == ["m-a"]),
        ]
        B.save_global_settings({"defaultThinkingLevel": "medium"})
        g = B.read_global_settings()
        checks += [
            ("el nivel por defecto se guarda en el settings global",
             g.get("defaultThinkingLevel") == "medium"),
            ("sin pisar el resto del fichero", g.get("theme") == "dark"),
        ]
        B.save_global_settings({"defaultThinkingLevel": None})
        checks.append(("y se puede volver al de pi borrando la clave",
                       "defaultThinkingLevel" not in B.read_global_settings()))

        # --- la confianza: pi mira PRIMERO trust.json y solo despues el
        # default, asi que el arreglo no es simetrico ---
        proj = Path(td) / "conrecursos"
        (proj / ".pi" / "skills").mkdir(parents=True)
        checks.append(("por defecto (ask) un proyecto con recursos pregunta",
                       B.needs_trust(str(proj)) is True))
        B.save_global_settings({"defaultProjectTrust": "always"})
        checks.append(("con 'always' pi ya confio: no se pregunta",
                       B.needs_trust(str(proj)) is False))
        B.save_global_settings({"defaultProjectTrust": "never"})
        checks.append(("con 'never' se sigue preguntando: lo guardado gana",
                       B.needs_trust(str(proj)) is True))
        B.save_global_settings({"defaultProjectTrust": None})

        # --- el mapa de razonamiento tiene TRES estados ---
        # null apaga el nivel (pi lo excluye en getSupportedThinkingLevels),
        # ausente lo manda tal cual, y una cadena lo traduce. Confundir null
        # con ausente activaba niveles que el servidor no acepta
        mp = {"off": "none", "minimal": None, "medium": "medium",
              "xhigh": "xhigh"}
        B.save_thinking_map("local", "m-a", mp)
        got = [x for x in json.loads((Path(td) / "models.json").read_text(
            encoding="utf-8"))["providers"]["local"]["models"]
            if x["id"] == "m-a"][0].get("thinkingLevelMap")
        B.save_thinking_map("local", "m-a", {"off": "none", "low": "  ",
                                             "medium": None})
        got2 = [x for x in json.loads((Path(td) / "models.json").read_text(
            encoding="utf-8"))["providers"]["local"]["models"]
            if x["id"] == "m-a"][0].get("thinkingLevelMap")
        checks += [
            ("guardar el mapa conserva los niveles apagados",
             got == mp and got.get("minimal", "AUSENTE") is None),
            ("un valor vacio si sale del mapa, un null no",
             "low" not in got2 and got2.get("medium", "AUSENTE") is None),
            ("un nivel inventado se rechaza",
             B.save_thinking_map("local", "m-a", {"turbo": "x"}) is not None),
        ]

        # --- las modalidades se editan: el servidor donde corre el modelo
        # puede ganar o perder vision, y el dato declarado deja de ser verdad
        B.save_model_params("local", "m-a", 32768, 4096, ["text", "image"])
        ed = [x for x in json.loads((Path(td) / "models.json").read_text(
            encoding="utf-8"))["providers"]["local"]["models"]
            if x["id"] == "m-a"][0]
        B.save_model_params("local", "m-a", 32768, 4096, ["text"])
        ed2 = [x for x in json.loads((Path(td) / "models.json").read_text(
            encoding="utf-8"))["providers"]["local"]["models"]
            if x["id"] == "m-a"][0]
        B.save_model_params("local", "m-a", 40000, 4096)
        ed3 = [x for x in json.loads((Path(td) / "models.json").read_text(
            encoding="utf-8"))["providers"]["local"]["models"]
            if x["id"] == "m-a"][0]
        checks += [
            ("se le puede declarar vision a un modelo existente",
             ed.get("input") == ["text", "image"]),
            ("y quitarsela cuando el servidor cambia",
             ed2.get("input") == ["text"]),
            ("sin tocarlas, se quedan como estaban",
             ed3.get("input") == ["text"] and ed3.get("contextWindow") == 40000),
        ]

        # --- modos de cola y transporte: solo valores que pi acepta ---
        checks += [
            ("los modos de cola son los de pi",
             B.QUEUE_MODES == ("all", "one-at-a-time")),
            ("y los transportes tambien",
             B.TRANSPORTS == ("sse", "websocket", "websocket-cached", "auto")),
        ]
        m = B.model_add("local", "vis", "Con vision", 32768, 4096, True,
                        ["text", "image"])
        md = json.loads((Path(td) / "models.json").read_text(encoding="utf-8"))
        added = [x for x in md["providers"]["local"]["models"]
                 if x["id"] == "vis"]
        checks += [
            ("un modelo se puede crear declarando vision",
             m is None and added and added[0].get("input") == ["text", "image"]),
            ("una modalidad inventada no entra",
             B.model_add("local", "v2", "x", 1000, 100, False,
                         ["text", "video"]) is None
             and [x for x in json.loads((Path(td) / "models.json").read_text(
                 encoding="utf-8"))["providers"]["local"]["models"]
                 if x["id"] == "v2"][0].get("input") == ["text"]),
        ]
    finally:
        del B.AGENT_DIR
        if old is not None:
            B.os.environ["PI_MODELS_JSON"] = old
    return checks


async def ui():
    checks = []
    shutil.rmtree(TMP, ignore_errors=True)
    td = str(TMP); TMP.mkdir(parents=True)
    seed(td)
    with Bridge(extra={"PI_AGENT_DIR": td}):
        async with Page(port=9431, width=1200, height=800) as p:
            js = p.js
            await p.go()
            await js("setLang('en')")

            # ---- rail fino: los dos iconos se cruzan con fundido ----
            await js("setFolded(true)")
            await asyncio.sleep(0.4)
            cross = await js("""(()=>{
              const c=document.querySelector('#slimLogo .cubemask');
              const h=document.querySelector('#slimLogo .hov');
              const cs=getComputedStyle(c), hs=getComputedStyle(h);
              return {cDisp:cs.display, hDisp:hs.display,
                cOp:cs.opacity, hOp:hs.opacity,
                cTr:cs.transitionDuration, hTr:hs.transitionDuration};})()""")
            checks += [
                ("los dos iconos del logo estan siempre montados",
                 cross["cDisp"] != "none" and cross["hDisp"] != "none"),
                ("se cruzan por opacidad, no por display",
                 cross["cOp"] == "1" and cross["hOp"] == "0"),
                ("y con transicion en ambos",
                 cross["cTr"].startswith("0.1")
                 and cross["hTr"].startswith("0.1")),
            ]

            # ---- rotulos, traducidos y con espera ----
            tips = await js("""(()=>{
              const ids=['slimNew','slimSearch','slimChat','slimTrash'];
              const out={};
              ids.forEach(i=>{const b=$('#'+i);
                out[i]={tip:b.dataset.tip||'', aria:b.getAttribute('aria-label')||'',
                  delay:getComputedStyle(b,'::after').transitionDelay};});
              return out;})()""")
            checks += [
                ("los cuatro iconos llevan rotulo",
                 all(tips[k]["tip"] for k in tips)),
                ("el rotulo sale tras una espera corta",
                 tips["slimNew"]["delay"].startswith("0.3")),
                ("y el aria-label dice lo mismo",
                 all(tips[k]["tip"] == tips[k]["aria"] for k in tips)),
            ]
            await js("setLang('es')")
            await asyncio.sleep(0.2)
            es = await js("$('#slimTrash').dataset.tip")
            await js("setLang('en')")
            checks.append(("los rotulos siguen al idioma", es == "Papelera"))

            # ---- con el rail fino, la hamburguesa sobra ----
            # en escritorio el logo del rail fino ya pliega y despliega, asi
            # que la hamburguesa no pinta nada en ninguno de los dos estados
            ham = await js("""({folded:getComputedStyle($('#railBtn')).display,
              open:(()=>{setFolded(false);
                return getComputedStyle($('#railBtn')).display;})()})""")
            checks.append(("en escritorio la hamburguesa no se ve nunca",
                           ham["folded"] == "none" and ham["open"] == "none"))

            # ---- el menu de clic derecho sale donde esta el raton ----
            await js("setFolded(false)")
            pos = await js("""(()=>{
              ctxAt={x:400,y:300};
              ctxPopup(document.body,[{label:'x',run:()=>{}}]);
              ctxAt=null;
              const r=document.querySelector('.ctxpop').getBoundingClientRect();
              return {x:r.left, y:r.top};})()""")
            await js("closeCtxPop()")
            checks.append(("el menu aparece junto al puntero",
                           abs(pos["x"] - 402) < 2 and abs(pos["y"] - 302) < 2))

            # ---- modelos: el borrar vive junto al lapiz y confirma (en Models) ----
            await js("onRpc({command:'get_available_models', data:{models:["
                     "{id:'m-a',name:'Model A',provider:'local',"
                     "contextWindow:32768,maxTokens:4096},"
                     "{id:'m-b',name:'Model B',provider:'local',"
                     "contextWindow:16384,maxTokens:2048}]}})")
            await js("$('#sheet').classList.add('open'); paintSheet('models')")
            await asyncio.sleep(0.3)
            rows = await js("""(()=>{
              const r=document.querySelector('#sheetBody .mrow');
              const pen=r.querySelector('.pen:not(.del)');
              const del=r.querySelector('.pen.del');
              const pr=pen.getBoundingClientRect(), dr=del.getBoundingClientRect();
              return {both:!!pen&&!!del, penRight:pr.right, delLeft:dr.left,
                pad:getComputedStyle(r).paddingRight};})()""")
            checks += [
                ("cada modelo trae lapiz y borrar", rows["both"]),
                ("sin pisarse, y con hueco reservado",
                 rows["penRight"] <= rows["delLeft"] + 1
                 and parseInt_(rows["pad"]) >= 60),
            ]
            await js("document.querySelector('#sheetBody .mrow .pen.del').click()")
            await asyncio.sleep(0.3)
            dlg = await js("""({open:$('#modal').classList.contains('open'),
              t:($('#modalTitle')||{}).textContent||''})""")
            checks.append(("el borrado de modelo pide confirmacion",
                           dlg["open"] and "Model A" in dlg["t"]))
            await js("closeModal()")
            await asyncio.sleep(0.25)

            # ---- nivel de razonamiento por defecto ----
            await js("onRpc({command:'get_available_thinking_levels',"
                     " data:{levels:['off','low','medium','high']}})")
            await js("onRpc({command:'thinking_default_get', data:{level:null}})")
            await js("paintSheet('model')")
            await asyncio.sleep(0.3)
            card = await js("""(()=>{
              const b=[...document.querySelectorAll('#sheetBody .pick')]
                .find(x=>/reasoning/i.test(x.textContent));
              return b ? {found:true, txt:b.textContent} : {found:false};})()""")
            checks.append(("ajustes globales ofrece el razonamiento por defecto",
                           card["found"]))
            # sin niveles cargados la pagina tiene que PEDIRLOS: con el nivel
            # de la sesion como respaldo se quedaba en esa sola opcion y no
            # los pedia nunca, asi que la lista nacia coja para siempre
            pide = await js("""(()=>{
              thinkLevels = []; state.thinking = 'medium';
              paintSheet('defthink');
              return [...document.querySelectorAll('#sheetBody .mrow')]
                .map(r=>r.textContent.trim());})()""")
            await js("onRpc({command:'get_available_thinking_levels',"
                     " data:{levels:['off','low','medium','high']}})")
            await asyncio.sleep(0.3)
            tras = await js("""({page:sheetPage,
              rows:[...document.querySelectorAll('#sheetBody .mrow')]
                     .map(r=>r.textContent.trim())})""")
            checks += [
                ("sin niveles cargados no se queda con el de la sesion",
                 pide == ["Use global", "medium"]),
                ("al llegar se repinta esta pagina, no el selector de sesion",
                 tras["page"] == "defthink" and "off" in tras["rows"]
                 and "high" in tras["rows"]),
            ]
            await js("goPage('defthink')")
            await asyncio.sleep(0.45)
            # "usar el de pi" es una fila mas de la lista, con su mismo hueco
            # de check: si fuera un pickBtn con icono saldrian dos ticks
            lv = await js("""(()=>{
              const rows=[...document.querySelectorAll('#sheetBody .mrow')];
              return {txt:rows.map(x=>x.textContent.trim()),
                slots:rows.every(x=>!!x.querySelector('.chkslot')),
                sel:rows.filter(x=>x.classList.contains('sel'))
                        .map(x=>x.textContent.trim())};})()""")
            checks += [
                ("lista los niveles tras la opcion de usar el de pi",
                 lv["txt"] == ["Use global", "off", "low", "medium", "high"]),
                ("todas las filas usan el mismo hueco de check", lv["slots"]),
                ("y solo una queda marcada", lv["sel"] == ["Use global"]),
            ]
            await js("[...document.querySelectorAll('#sheetBody .mrow')]"
                     ".find(x=>x.textContent.trim()==='high').click()")
            await asyncio.sleep(0.6)
            saved = json.loads(
                (Path(td) / "settings.json").read_text(encoding="utf-8"))
            checks.append(("elegirlo lo escribe en el settings global",
                           saved.get("defaultThinkingLevel") == "high"))

            # ---- la carpeta del usuario se pinta como ~ ----
            t = await js("""(()=>{
              const old = state.home;
              state.home = 'C:/Users/tester';
              const cases = {
                bajo:  tilde('C:/Users/tester/Desktop/Python/pi-remote'),
                barras:tilde('C:\\\\Users\\\\tester\\\\Desktop\\\\x'),
                exacto:tilde('C:/Users/tester'),
                fuera: tilde('D:/otro/sitio'),
                otro:  tilde('C:/Users/testerX/cosa')};
              state.recent = [{name:'pi-remote',
                path:'C:/Users/tester/Desktop/Python/pi-remote'}];
              paintRail();
              const hint = document.querySelector('#recents .proj small');
              state.home = old;
              return {cases, row: hint ? hint.textContent : ''};})()""")
            c = t["cases"]
            checks += [
                ("la ruta bajo el home se acorta con ~",
                 c["bajo"] == "~/Desktop/Python/pi-remote"),
                ("tambien con barras de Windows",
                 c["barras"] == "~/Desktop/x"),
                ("el home exacto es ~", c["exacto"] == "~"),
                ("lo que no cuelga del home no se toca",
                 c["fuera"] == "D:/otro/sitio"
                 and c["otro"] == "C:/Users/testerX/cosa"),
                ("y las filas de proyecto lo usan",
                 t["row"].startswith("~/Desktop")),
            ]

            # ---- el nombre del proyecto sale de la ruta, en los dos sistemas ----
            pn = await js(r"""({
              win:  projName('C:\\Users\\x\\Desktop\\Python\\pi-remote'),
              posix:projName('/home/x/code/StemScore'),
              cola: projName('C:\\Users\\x\\Desktop\\sandbox\\'),
              vacio:projName('')})""")
            checks += [
                # el separador de Windows es el caso normal aqui: con un regex
                # mal escapado no partia nada y salia la ruta entera
                ("el nombre sale de una ruta de Windows",
                 pn["win"] == "pi-remote"),
                ("y de una ruta POSIX", pn["posix"] == "StemScore"),
                ("con barra final tambien", pn["cola"] == "sandbox"),
                ("sin ruta, vacio", pn["vacio"] == ""),
            ]

            # ---- la hora va en 24h, sin segundos ----
            fmt = await js("""(()=>{
              const t = new Date(2026, 8, 22, 21, 5, 46).getTime();
              return {en: when(t), es:(()=>{const o=lang;return when(t);})()};
              })()""")
            checks += [
                ("la hora va en 24h", "21:05" in fmt["en"]
                 and "PM" not in fmt["en"] and "pm" not in fmt["en"]),
                ("y sin segundos", "46" not in fmt["en"]),
            ]

            # ---- el separador de la raiz del menu se ve ----
            await js("$('#sheet').classList.add('open'); paintSheet('root')")
            await asyncio.sleep(0.3)
            sep = await js("""(()=>{
              const d = document.querySelector('#sheetBody .sdiv');
              if(!d) return {found:false};
              const cs = getComputedStyle(d);
              return {found:true, h:cs.height, bg:cs.backgroundColor,
                ref:getComputedStyle(document.documentElement)
                     .getPropertyValue('--rule').trim()};})()""")
            checks += [
                ("la raiz del menu separa sus dos grupos", sep["found"]),
                ("con una linea de verdad, no solo aire",
                 sep.get("h") == "1px"
                 and sep.get("bg") not in ("rgba(0, 0, 0, 0)", "transparent")),
            ]

            # ---- la papelera dice que esta cargando y si falla, lo dice ----
            await js("$('#sheet').classList.remove('open')")
            await js("openTrash()")
            load = await js("""(()=>{
              const l = $('#trashList');
              return {spin: !!l.querySelector('.sspin'),
                grab: !!document.querySelector('#trashView .grab')};})()""")
            await asyncio.sleep(0.8)
            done = await js("!!$('#trashList').querySelector('.sspin')")
            fail = await js("""(async()=>{
              const f = window.fetch;
              window.fetch = () => Promise.reject(new Error('sin red'));
              await loadTrash();
              window.fetch = f;
              const t = $('#trashList').textContent;
              return t;})()""")
            # las filas de la papelera: proyecto y fecha, no la ruta cruda
            row = await js("""(()=>{
              const r = trashRow({label:'una sesion', mtime:1758500000,
                cwd:'C:\\\\Users\\\\x\\\\Desktop\\\\Python\\\\pi-remote',
                path:'/x/y.jsonl'});
              const p = r.querySelector('.tp').textContent;
              const pad = getComputedStyle(
                document.querySelector('#trashView .sbar2')).paddingTop;
              return {p, pad};})()""")
            checks += [
                ("la fila de papelera dice proyecto y fecha",
                 row["p"].startswith("pi-remote")
                 and "\u00b7" in row["p"] and ":" in row["p"]),
                ("y no la ruta cruda", "Users" not in row["p"]),
                ("la cabecera no reserva el notch dentro de la hoja",
                 float(row["pad"].replace("px", "")) < 12),
                ("mientras carga gira un spinner", load["spin"]),
                ("y lleva la pill de arrastre", load["grab"]),
                ("al llegar los datos el spinner se va", done is False),
                ("si el fetch falla se dice, no se finge vacia",
                 "Could not load" in fail),
            ]
            await js("closeTrash()")

            # ---- editar modelo: el mapa va con cromo de campo ----
            await js("""editModel = {provider:'local', id:'m-a',
              name:'Model A', contextWindow:32768, maxTokens:4096,
              input:['text','image']};
              onRpc({command:'thinking_map_get', data:{
                map:{off:'none', minimal:null, medium:'medium', xhigh:'xhigh'},
                levels:['off','minimal','low','medium','high','xhigh','max']}});
              sheetStack=[]; paintSheet('modelEdit');""")
            await asyncio.sleep(0.3)
            me = await js("""(()=>{
              // el ultimo campo de eleccion es el mapa (el primero es el
              // razonamiento por modelo)
              const sels=document.querySelectorAll('#sheetBody .mfield.sel');
              const sel=sels[sels.length-1];
              if(!sel) return {found:false};
              const b=sel.querySelector('button');
              const txt=document.querySelector('#sheetBody .mfield:not(.sel) input');
              const rb=b.getBoundingClientRect(), rt=txt.getBoundingClientRect();
              const cb=getComputedStyle(b), ct=getComputedStyle(txt);
              return {found:true, val:b.textContent,
                dx:Math.abs(rb.left-rt.left), dw:Math.abs(rb.width-rt.width),
                dh:Math.abs(rb.height-rt.height),
                radio:cb.borderRadius===ct.borderRadius,
                picks:document.querySelectorAll('#sheetBody .pick').length,
                sameFont:(()=>{ // contra una fila de navegacion de verdad
                  const probe=pickBtn({label:'x', chevron:true, run:()=>{}});
                  document.body.appendChild(probe);
                  const a=getComputedStyle(b), c=getComputedStyle(probe);
                  const f=a.fontFamily===c.fontFamily;
                  window.__sz = a.fontSize===c.fontSize;
                  probe.remove(); return f;})(),
                sameSize:window.__sz};})()""")
            checks += [
                ("el mapa se alinea con los campos del modelo",
                 me["found"] and me.get("dx", 9) < 1 and me.get("dw", 9) < 1
                 and me.get("dh", 9) < 2 and me.get("radio")),
                ("y no queda ninguna fila de menu suelta",
                 me.get("picks") == 0),
                # el campo dice su nombre y nada mas: sin resumen que
                # pudiera leerse como los niveles disponibles (esa cuenta la
                # hace pi, no el cliente)
                ("el campo dice su nombre, sin cifras que interpretar",
                 me.get("val", "").strip() == "Reasoning map"),
                # coherencia: se lee igual que las 15 filas de navegacion de
                # la app (misma familia y tamano), aunque el contenedor sea
                # de campo para poder alinearse dentro de un formulario
                ("y se lee como las demas filas que abren subpagina",
                 me.get("sameFont") is True and me.get("sameSize") is True),
            ]

            # ---- comportamiento del agente: cola y transporte ----
            await js("onRpc({command:'agent_prefs_get', data:{"
                     "steeringMode:'all', followUpMode:'all',"
                     "transport:'auto',"
                     "queueModes:['all','one-at-a-time'],"
                     "transports:['sse','websocket','websocket-cached','auto']}})")
            await js("$('#sheet').classList.add('open');"
                     " sheetStack=[]; paintSheet('agentprefs')")
            await asyncio.sleep(0.3)
            prefs = await js("""(()=>{
              const rows=[...document.querySelectorAll('#sheetBody .pick')];
              return rows.map(r=>r.textContent);})()""")
            checks.append(("ofrece las dos colas y el transporte",
                           len(prefs) == 3
                           and any("Queue while working" in x for x in prefs)
                           and any("Follow-up" in x for x in prefs)
                           and any("Transport" in x for x in prefs)))
            await js("prefKey='steeringMode'; prefList='queueModes';"
                     " goPage('agentpref1')")
            await asyncio.sleep(0.45)
            opts = await js("""(()=>{
              const rows=[...document.querySelectorAll('#sheetBody .mrow')];
              return {txt:rows.map(r=>r.textContent.trim()),
                sel:rows.filter(r=>r.classList.contains('sel'))
                        .map(r=>r.textContent.trim())};})()""")
            checks.append(("los modos se leen en palabras, no en claves",
                           opts["txt"] == ["All at once", "One at a time"]
                           and opts["sel"] == ["All at once"]))
            # elegir manda el comando de verdad: acaba en el settings global
            await js("""[...document.querySelectorAll('#sheetBody .mrow')]
              .find(r=>/One at a time/.test(r.textContent)).click()""")
            await asyncio.sleep(0.7)
            cfg = json.loads(
                (Path(td) / "settings.json").read_text(encoding="utf-8"))
            checks.append(("elegir un modo lo escribe en el settings global",
                           cfg.get("steeringMode") == "one-at-a-time"))

            # un puente sin reiniciar no conoce el comando: sin mirar el error
            # se guardaba su {error:...} como si fueran los ajustes y la pagina
            # salia con "undefined" en las tres filas y las listas vacias
            await js("onRpc({command:'agent_prefs_get',"
                     " data:{error:'command not allowed'}})")
            await js("sheetStack=[]; paintSheet('agentprefs')")
            await asyncio.sleep(0.25)
            bad = await js("""({
              warn:(document.querySelector('#sheetBody .cwarn')||{}).textContent||'',
              undef:$('#sheetBody').textContent.includes('undefined'),
              rows:document.querySelectorAll('#sheetBody .pick').length})""")
            checks += [
                # "command not allowed" es jerga del protocolo: al usuario se
                # le dice lo que tiene que hacer, no el codigo de error
                ("si el puente no conoce el comando, se dice que hacer",
                 "restarted" in bad["warn"]
                 and "command not allowed" not in bad["warn"]),
                ("y no se pinta 'undefined' en ninguna fila",
                 bad["undef"] is False and bad["rows"] == 0),
            ]
            # el aviso de reinicio habla de pi remote, no de la jerga /restart
            note = await js("""(()=>{
              onRpc({command:'agent_prefs_get', data:{steeringMode:'all',
                followUpMode:'all', transport:'auto',
                queueModes:['all','one-at-a-time'],
                transports:['sse','auto']}});
              paintSheet('agentprefs');
              return (document.querySelector('#sheetBody .chelp')||{})
                .textContent||'';})()""")
            checks.append(("el aviso dice reiniciar pi remote, sin jerga",
                           "restarting pi remote" in note
                           and "/restart" not in note))
            await js("$('#sheet').classList.remove('open')")

            # ---- el teclado no se lleva la cabecera ----
            kb = await js("""(()=>{
              scrollTo(0, 0);
              const before=$('.plate').getBoundingClientRect().top;
              // simular el desplazamiento del viewport de maquetacion
              if(window.visualViewport) dispatchEvent(new Event('resize'));
              return {before, y:scrollY};})()""")
            checks.append(("la cabecera queda a la vista, sin scroll de pagina",
                           kb["before"] >= -1 and kb["y"] == 0))
    return checks


def parseInt_(v):
    try:
        return float(str(v).replace("px", ""))
    except ValueError:
        return 0.0


async def main():
    return backend() + await ui()


raise SystemExit(report(asyncio.run(main())))
