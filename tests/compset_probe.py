"""Pagina de contexto/compaction: escribe el settings.json GLOBAL de pi.

Las reglas son de pi (core/compaction): corta en ventana - reserva y el resumen
dispone de min(0.8*reserva, maxTokens). De ahi el codo: pasado maxTokens*1.25
la reserva no da mas resumen, solo adelanta el corte. Los presets mueven solo
el contexto reciente; la reserva va siempre al codo.

Solo global a proposito: pi LEE compaction del merge global+proyecto pero su
unico setter escribe en el global.
"""
import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from harness import Bridge, Page, report

TMP = Path(tempfile.gettempdir()) / "compset_probe_tmp"
W, MT = 150000, 16384
KNEE = int(MT * 1.25)                      # 20480


def seed(td):
    """Un agent dir con un models.json y ajustes previos que no se pueden
    perder al escribir compaction."""
    (Path(td) / "models.json").write_text(json.dumps({"providers": {
        "local": {"baseUrl": "http://x/v1", "models": [
            {"id": "m27", "contextWindow": W, "maxTokens": MT,
             "reasoning": True}]}}}), encoding="utf-8")
    (Path(td) / "settings.json").write_text(
        json.dumps({"theme": "dark", "tuiMode": "regular"}), encoding="utf-8")


def backend():
    import pi_web_bridge as B
    checks = []
    shutil.rmtree(TMP, ignore_errors=True)
    td = str(TMP); TMP.mkdir(parents=True)
    seed(td)
    B.AGENT_DIR = Path(td)
    old_models = B.os.environ.pop("PI_MODELS_JSON", None)
    try:
        checks.append(("los defaults son los de pi",
                       B.DEFAULT_COMPACTION == {"enabled": True,
                                                "reserveTokens": 16384,
                                                "keepRecentTokens": 20000}))
        checks.append(("model_limits saca ventana y maxTokens del modelo",
                       B.model_limits("local", "m27") == (W, MT)))
        checks.append(("modelo inexistente da (None, None)",
                       B.model_limits("local", "nope") == (None, None)))

        err = B.save_global_settings({"compaction": {
            "enabled": True, "reserveTokens": KNEE, "keepRecentTokens": 20000}})
        d = json.loads((Path(td) / "settings.json").read_text(encoding="utf-8"))
        checks += [
            ("guardar no da error", err is None),
            ("compaction queda escrito",
             d.get("compaction", {}).get("reserveTokens") == KNEE),
            ("el resto del fichero se conserva",
             d.get("theme") == "dark" and d.get("tuiMode") == "regular"),
            ("el puente lo relee",
             B.read_global_settings()["compaction"]["keepRecentTokens"] == 20000),
        ]
        # borrar una clave con None, como hace save_project_settings
        B.save_global_settings({"compaction": None})
        checks.append(("None borra la clave",
                       "compaction" not in B.read_global_settings()
                       and B.read_global_settings().get("theme") == "dark"))
    finally:
        del B.AGENT_DIR
        if old_models is not None:
            B.os.environ["PI_MODELS_JSON"] = old_models
    return checks


async def ui():
    checks = []
    shutil.rmtree(TMP, ignore_errors=True)
    td = str(TMP); TMP.mkdir(parents=True)
    seed(td)
    with Bridge(extra={"PI_AGENT_DIR": td}):
        async with Page(port=9425) as p:
            js = p.js
            await p.go()
            await js("setLang('en')")
            # la pagina se alimenta de compaction_get; inyectarlo hace el
            # probe determinista (igual que model_probe con los modelos)
            await js("onRpc({command:'compaction_get', data:{global:{},"
                     "project:{}, window:%d, maxTokens:%d,"
                     "defaults:{enabled:true,reserveTokens:16384,"
                     "keepRecentTokens:20000}}})" % (W, MT))
            await js("paintSheet('compaction')")
            await asyncio.sleep(0.3)

            # ---- las reglas de pi, calculadas en el cliente ----
            calc = await js("({knee:compKnee(), sum:compSummary(20480),"
                            " sumCap:compSummary(40000),"
                            " cycle:compCycle(20480,10000),"
                            " pAggr:compPresetK('aggr'),"
                            " pBal:compPresetK('bal'),"
                            " pCons:compPresetK('cons')})")
            checks += [
                ("el codo es maxTokens * 1.25", calc["knee"] == KNEE),
                ("el resumen es 0.8 * reserva", calc["sum"] == 16384),
                ("y topa en maxTokens", calc["sumCap"] == MT),
                ("el ciclo descuenta resumen y reciente",
                 calc["cycle"] == (W - KNEE) - (16384 + 10000)),
                ("balanced reproduce el default de pi", calc["pBal"] == 20000),
                ("aggressive es la mitad y conservative el doble",
                 calc["pAggr"] == 10000 and calc["pCons"] == 40000),
            ]

            # ---- estructura ----
            ui0 = await js("""(()=>{
              const b=$('#sheetBody');
              return {sw:!!b.querySelector('.sw'),
                presets:[...b.querySelectorAll('.preset')].map(x=>x.dataset.p),
                pSub:[...b.querySelectorAll('.preset small')].length,
                pTxt:[...b.querySelectorAll('.preset')].map(x=>x.textContent),
                helps:[...b.querySelectorAll('.chelp')].map(x=>x.textContent),
                sliders:[...b.querySelectorAll('input[type=range]')].map(s=>s.id),
                foot:(b.querySelector('.cfoot')||{}).textContent||'',
                ok:$('#sheetOk').hidden};})()""")
            checks += [
                ("hay toggle, tres presets y dos sliders",
                 ui0["sw"] and ui0["presets"] == ["aggr", "bal", "cons"]
                 and ui0["sliders"] == ["compR", "compK"]),
                ("los presets van sin subtitulo",
                 ui0["pSub"] == 0
                 and ui0["pTxt"] == ["Aggressive", "Balanced", "Conservative"]),
                ("cada slider lleva su explicacion debajo",
                 len(ui0["helps"]) == 2
                 and ui0["helps"][0].startswith("Space kept free")
                 and ui0["helps"][1].startswith("How much of the latest")),
                ("la linea de abajo dice el reasoning del modelo",
                 ui0["foot"].startswith("model reasoning:")),
                ("sin cambios, el check esta oculto", ui0["ok"] is True),
            ]

            # ---- el preset mueve los dos sliders (con spline) ----
            await js("[...document.querySelectorAll('.preset')]"
                     ".find(b=>b.dataset.p==='cons').click()")
            await asyncio.sleep(0.12)
            mid = await js("({r:+$('#compR').value, k:+$('#compK').value})")
            await asyncio.sleep(0.5)
            end = await js("""({r:+$('#compR').value, k:+$('#compK').value,
              rn:$('#compRn').value, kn:$('#compKn').value,
              sel:[...document.querySelectorAll('.preset.sel')]
                    .map(x=>x.dataset.p), ok:$('#sheetOk').hidden})""")
            checks += [
                ("a mitad del tween los sliders van en camino",
                 0 < mid["k"] < 40000 and mid["k"] != 20000),
                ("al acabar caen en el valor exacto",
                 end["r"] == KNEE and end["k"] == 40000),
                ("el numero viaja con el slider",
                 end["rn"] == str(KNEE) and end["kn"] == "40000"),
                ("el preset aplicado queda marcado", end["sel"] == ["cons"]),
                ("con cambios, aparece el check", end["ok"] is False),
            ]

            # ---- el slider topa en el codo: no hay zona muerta ----
            top = await js("""({max:+$('#compR').max,
              hint:$('#compHint').textContent})""")
            # el numero no puede meter mas de lo que el slider permite
            await js("$('#compRn').value='99000'; $('#compRn').onchange()")
            await asyncio.sleep(0.15)
            clamp = await js("({r:compDraft.reserveTokens,"
                             " n:$('#compRn').value})")
            await js("$('#compR').value=%d; $('#compR').oninput()" % 8192)
            await asyncio.sleep(0.15)
            low = await js("$('#compHint').textContent")
            checks += [
                ("el slider de la reserva topa en el codo", top["max"] == KNEE),
                ("teclear de mas se recorta al codo",
                 clamp["r"] == KNEE and clamp["n"] == str(KNEE)),
                ("el presupuesto sube en todo el recorrido, sin zona muerta",
                 "16k" in top["hint"] and "7k" in low),
            ]
            await js("$('#compR').value=%d; $('#compR').oninput()" % KNEE)
            await asyncio.sleep(0.15)

            # ---- el reparto suma la ventana entera, con su leyenda ----
            bar = await js("""(()=>{
              const w=[...document.querySelectorAll('.cbar > i')]
                .map(x=>parseFloat(x.style.width));
              // el punto tiene que VERSE: medir el color pintado, no que exista
              const lg=[...document.querySelectorAll('#compLegend span')]
                .map(x=>{const d=x.querySelector('i');
                  const cs=d?getComputedStyle(d):null;
                  return {dot:!!d, round:cs?cs.borderRadius:'',
                          bg:cs?cs.backgroundColor:'',
                          size:cs?cs.width:'',
                          val:(x.querySelector('b')||{}).textContent||''};});
              const barc=[...document.querySelectorAll('.cbar > i')]
                .map(x=>getComputedStyle(x).backgroundColor);
              return {n:w.length, total:w.reduce((a,b)=>a+b,0), lg, barc};})()""")
            clear = ("rgba(0, 0, 0, 0)", "transparent", "")
            checks += [
                ("los cuatro tramos reparten el 100% de la ventana",
                 bar["n"] == 4 and abs(bar["total"] - 100) < 0.5),
                ("la leyenda trae los cuatro, con circulo y valor",
                 len(bar["lg"]) == 4
                 and all(x["dot"] and x["val"] for x in bar["lg"])
                 and all("50%" in x["round"] for x in bar["lg"])),
                ("las bolitas se pintan de verdad (no transparentes)",
                 all(x["bg"] not in clear and x["size"] != "0px"
                     for x in bar["lg"])),
                ("y cada una lleva el color de su tramo",
                 [x["bg"] for x in bar["lg"]] == bar["barc"]),
            ]

            # ---- salir con cambios pregunta ----
            await js("$('#sheetBack').click()")
            await asyncio.sleep(0.3)
            ask = await js("""({open:!$('#modal').hidden,
              txt:($('#modalTitle')||{}).textContent||''})""")
            checks.append(("el back con cambios pregunta si descartar",
                           ask["open"] and "Discard" in ask["txt"]))
            await js("$('#modalOk').click()")
            await asyncio.sleep(0.3)

            # ---- el check escribe el settings.json global ----
            await js("paintSheet('compaction')")
            await asyncio.sleep(0.2)
            await js("[...document.querySelectorAll('.preset')]"
                     ".find(b=>b.dataset.p==='aggr').click()")
            await asyncio.sleep(0.6)
            await js("$('#sheetOk').click()")
            await asyncio.sleep(0.3)
            await js("$('#modalOk').click()")
            await asyncio.sleep(0.6)
            saved = json.loads(
                (Path(td) / "settings.json").read_text(encoding="utf-8"))
            c = saved.get("compaction") or {}
            checks += [
                ("el check escribe compaction en el settings global",
                 c.get("reserveTokens") == KNEE
                 and c.get("keepRecentTokens") == 10000
                 and c.get("enabled") is True),
                ("sin tocar el resto del fichero", saved.get("theme") == "dark"),
            ]

            # ---- el toggle no repinta: el knob tiene que poder animar ----
            await js("paintSheet('compaction')")
            await asyncio.sleep(0.25)
            anim = await js("""(()=>{
              const sw=document.querySelector('#sheetBody .sw');
              const bd=document.querySelector('.cbody');
              const before=sw;
              sw.click();
              return {same:document.querySelector('#sheetBody .sw')===before,
                checked:sw.getAttribute('aria-checked'),
                open:bd.classList.contains('on'),
                trans:getComputedStyle(bd).transitionDuration,
                knob:getComputedStyle(sw.querySelector('.knob'))
                       .transitionDuration};})()""")
            checks += [
                ("el toggle no reconstruye el nodo (si no, no anima)",
                 anim["same"] is True),
                ("apagar deja el switch en false",
                 anim["checked"] == "false"),
                ("y pliega el cuerpo, con transicion",
                 anim["open"] is False
                 and anim["trans"].startswith("0.3")),
                ("el knob conserva su transicion",
                 anim["knob"].startswith("0.2")),
            ]
            # el cuerpo sigue en el DOM, plegado: por eso puede animar
            folded = await js("""({inDom:document.querySelectorAll(
              '#sheetBody input[type=range]').length,
              rows:getComputedStyle(document.querySelector('.cbody'))
                     .gridTemplateRows,
              foot:!!document.querySelector('#sheetBody .cfoot')})""")
            checks.append(("plegado conserva los sliders y la lectura",
                           folded["inDom"] == 2 and folded["foot"]
                           and folded["rows"] != "0px"))

            # ---- el check sale con fundido, no de golpe ----
            await js("$('#sheetBack').click()")
            await asyncio.sleep(0.05)
            await js("if(!$('#modal').hidden) $('#modalOk').click()")
            await asyncio.sleep(0.3)
            await js("paintSheet('compaction')")
            await asyncio.sleep(0.2)
            await js("compSetOk(true)")
            shown = await js("({h:$('#sheetOk').hidden,"
                             " out:$('#sheetOk').classList.contains('out')})")
            await js("compSetOk(false)")
            mid2 = await js("({h:$('#sheetOk').hidden,"
                            " out:$('#sheetOk').classList.contains('out')})")
            await asyncio.sleep(0.35)
            gone = await js("({h:$('#sheetOk').hidden,"
                            " out:$('#sheetOk').classList.contains('out')})")
            checks += [
                ("el check aparece visible", shown["h"] is False
                 and shown["out"] is False),
                ("al ocultarlo se funde antes de irse",
                 mid2["h"] is False and mid2["out"] is True),
                ("y acaba oculto y limpio",
                 gone["h"] is True and gone["out"] is False),
            ]

            # ---- un valor mayor puesto a mano en el fichero no se falsea ----
            await js("onRpc({command:'compaction_get',"
                     " data:{global:{enabled:true,reserveTokens:40000,"
                     "keepRecentTokens:20000}, project:{}, window:%d,"
                     " maxTokens:%d, defaults:{}}})" % (W, MT))
            await js("paintSheet('compaction')")
            await asyncio.sleep(0.25)
            legacy = await js("""({max:+$('#compR').max, val:+$('#compR').value,
              n:$('#compRn').value, ok:$('#sheetOk').hidden})""")
            checks.append(
                ("un valor heredado por encima del codo se sigue mostrando",
                 legacy["max"] == 40000 and legacy["val"] == 40000
                 and legacy["n"] == "40000" and legacy["ok"] is True))

            # ---- el puente que no conoce el comando no deja media pagina ----
            await js("onRpc({command:'compaction_get',"
                     " data:{error:'command not allowed'}})")
            await js("paintSheet('compaction')")
            await asyncio.sleep(0.2)
            err = await js("""({warn:(document.querySelector(
              '#sheetBody .cwarn')||{}).textContent||'',
              sliders:document.querySelectorAll(
                '#sheetBody input[type=range]').length,
              sw:!!document.querySelector('#sheetBody .sw')})""")
            # el error crudo del protocolo se traduce a lo que hay que hacer
            checks.append(("el error del puente se dice, no se disfraza",
                           "restarted" in err["warn"]
                           and err["sliders"] == 0 and not err["sw"]))
    return checks


async def main():
    return backend() + await ui()


raise SystemExit(report(asyncio.run(main())))
