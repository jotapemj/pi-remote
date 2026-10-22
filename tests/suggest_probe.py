"""Sugerencias de respuesta (v0.106.0): al asentar el turno, el puente las
pide DIRECTO al modelo (thinking off, el mismo canal del resumen al parar).
No viajan pegadas al prompt y la respuesta del turno NO se parsea: un formato
raro cuesta una fila menos, no un chat roto, y el .jsonl queda limpio.
Llegan como item propio (kind 'suggest') bajo la respuesta que las genero;
clic = enviar ese mensaje. Se mide el DOM pintado con Chrome, contra un mini
servidor OpenAI-compatible que registra las peticiones y devuelve tres lineas
adornadas (numero, vineta, negrita y marcador <hint:> del diseno viejo).
Mientras se piden, aro de carga (state.suggesting) en el sitio de las filas.
Sin baseUrl en el proveedor no hay a quien preguntar: state.canSuggest=False,
el interruptor sale apagado con el motivo y no sale ni una llamada extra.
Las sesiones grabadas con el diseno viejo siguen pintando sus filas desde el
texto: se comprueba ahi el parser legado del cliente.
"""
import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from harness import Bridge, FakeProject, Page, report

# El modelo adorna a proposito: numero, vineta + negrita y un marcador viejo.
# El puente tiene que dejar las tres filas limpias.
SAYS = ("1. Vale, haz el push.\n- **Espera, revisa antes.**\n"
        "<hint: Muestrame el diff.>")
ROWS = ["Vale, haz el push.", "Espera, revisa antes.", "Muestrame el diff."]
# respuesta de fake_pi al prompt limpio: si el puente inyectara la instruccion
# vieja, fake_pi contestaria con marcadores y estas filas serian otras
ANSWER = "Looking at"


class Model(BaseHTTPRequestHandler):
    """Un OpenAI-compatible minimo: content plano, sin razonar. Duerme para
    que el aro de carga sea medible y registra la peticion completa."""

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("content-length", 0))
        req = json.loads(self.rfile.read(n).decode("utf-8"))
        with open(os.environ["MODEL_LOG"], "a", encoding="utf-8") as fh:
            fh.write(json.dumps(req, ensure_ascii=True) + "\n")
        time = float(os.environ.get("MODEL_SLEEP", "0.6"))
        if time:
            threading.Event().wait(time)
        body = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": SAYS}}],
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_model(log, sleep="0.6"):
    srv = HTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["MODEL_LOG"] = str(log)
    os.environ["MODEL_SLEEP"] = sleep
    return srv, srv.server_port


def write_models(path, base=None):
    """Catalogo de pi con el provider "local" (el que trae fake_pi por
    defecto). Sin base: provider sin baseUrl, el caso sin endpoint."""
    prov = {"apiKey": "sk-test"}
    if base:
        prov["baseUrl"] = base
    path.write_text(json.dumps({"providers": {"local": prov}}),
                    encoding="utf-8")
    return str(path)


def calls(log):
    if not os.path.exists(log):
        return []
    with open(log, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


async def until(js, cond, timeout=10.0):
    for _ in range(int(timeout * 10)):
        if await js(cond):
            return True
        await asyncio.sleep(0.1)
    return False


async def send_turn(js, text):
    """El camino real: el compositor manda el mensaje con el flag de
    sugerencias puesto y el puente lo lanza."""
    await js("box.value = %r; submit()" % text)
    assert await until(js, "state.running === true", 8), "no arranco el turno"


async def settle(js):
    assert await until(js, "state.running === false", 25), "no asento"


async def phase_with_endpoint(p, js, checks, proj, log):
    await p.go()
    await js("setLang('es')")
    await js("send({type:'open_project', path:%s})"
                 % json.dumps(proj.path))
    assert await until(js, "state.cwd !== null", 8), "no abrio el proyecto"
    # el provider llega en un estado posterior: hasta que no se sabe, el
    # puente no puede decir si tiene URL propia
    await until(js, "state.modelProvider !== null", 8)
    checks.append(("con baseUrl, el puente dice que puede sugerir",
                   await js("state.canSuggest") is True))

    # camino viejo: sesiones ya grabadas, los marcadores viven dentro del
    # texto de la respuesta -> ahi el parser legado sigue pintando las filas
    await js("setSuggest(true);")
    await js("feed.innerHTML=''; nodes.clear();"
             " render({id:-5, kind:'assistant', streaming:false,"
             " text:'Hecho. Cuando digas, push.\\n<hint: Viejo A>\\n"
             "<hint: Viejo B>', t:Date.now()}); paint(); placeActions();")
    legacy = await js("(() => {"
                      " const m = document.querySelector('.said');"
                      " return {"
                      " rows: [...document.querySelectorAll"
                      "('.suggests.derived .stext')].map(e => e.textContent),"
                      " msg: m ? m.innerText : ''};})()")
    print("  legado:", json.dumps(legacy, ensure_ascii=True))
    checks += [
        ("sesion vieja: sus filas salen del texto, como antes",
         legacy["rows"] == ["Viejo A", "Viejo B"]),
        ("sesion vieja: los marcadores no se leen",
         "<hint" not in legacy["msg"]),
    ]

    # OFF: interruptor apagado -> ni llamada al modelo, ni filas
    await js("setSuggest(false); feed.innerHTML=''; nodes.clear();")
    await send_turn(js, "apagado")
    await settle(js)
    await asyncio.sleep(0.5)
    checks += [
        ("OFF: no se molesta al modelo", len(calls(log)) == 0),
        ("OFF: no hay filas de sugerencia",
         await js("document.querySelectorAll('.suggests .sug').length") == 0),
    ]

    # ON: aro de carga en el sitio exacto y tres filas limpias al llegar
    await js("setSuggest(true)")
    await js("navigator.clipboard.writeText = t => {"
             " window.__copied = t; return Promise.resolve(); };")
    await send_turn(js, "hola")
    await settle(js)
    got_ring = await until(js, "!!document.querySelector('.suggests.skel')", 2)
    ring = await js("(() => {"
                    " const w = document.querySelector('.suggests.skel');"
                    " if(!w) return null;"
                    " const b = [...w.querySelectorAll('.stext')];"
                    " return {n: b.length,"
                    " bars: b.every(x => getComputedStyle(x).display !== 'none'"
                    "  && x.getBoundingClientRect().width > 10),"
                    " dead: [...w.querySelectorAll('.sug')].every(x =>"
                    "  getComputedStyle(x).pointerEvents === 'none')};})()")
    print("  carga:", json.dumps(ring, ensure_ascii=True))
    checks.append(("mientras se piden: aro de carga en el sitio de las filas",
                   got_ring and ring and ring["n"] == 3 and ring["bars"] is True
                   and ring["dead"] is True))
    got = await until(js, "document.querySelectorAll"
                         "('.suggests.src .sug').length === 3", 10)
    rows = await js("[...document.querySelectorAll"
                    "('.suggests.src .sug .stext')].map(e => e.textContent)")
    print("  filas:", json.dumps(rows, ensure_ascii=True))
    checks += [
        ("ON: pintan tres filas", got is True),
        ("limpias: cae numero, vineta, negrita y el marcador viejo",
         rows == ROWS),
        ("al llegar las filas se apaga el aro de carga",
         await js("document.querySelectorAll('.suggests.skel').length") == 0),
        ("el puente dice que ya no esta pidiendo",
         await js("state.suggesting") is False),
    ]

    reqs = calls(log)
    instr = reqs[0]["messages"][0]["content"] if reqs else ""
    tpl = (reqs[0].get("chat_template_kwargs") or {}) if reqs else {}
    print("  peticion:", json.dumps(
        {"n": len(reqs), "model": reqs[0].get("model") if reqs else None,
         "think": tpl.get("enable_thinking"),
         "toks": reqs[0].get("max_tokens") if reqs else None,
         "instr": instr[:200]}, ensure_ascii=True))
    checks += [
        ("ON: una sola llamada, directa al endpoint", len(reqs) == 1),
        ("usa el modelo activo",
         bool(reqs) and reqs[0].get("model") == "qwen3-8b"),
        # thinking off: un modelo que se pone a pensar gasta el presupuesto en
        # razonamiento y devuelve content vacio
        ("con razonamiento apagado", tpl.get("enable_thinking") is False),
        # contexto minimo: el mensaje del usuario (ancla de idioma) y la
        # respuesta que se acabo de leer; el turno anterior no viaja
        ("ve el mensaje del usuario de este turno",
         "hola" in instr and "apagado" not in instr),
        ("ve la respuesta que el usuario acabo de leer", ANSWER in instr),
    ]

    pos = await js("(() => {"
                   " const all = [...feed.querySelectorAll('.turn')];"
                   " const rows = [...feed.querySelectorAll('.suggests.src')].pop();"
                   " if(!rows) return {err:'no rows'};"
                   " const acts = [...feed.querySelectorAll('.msgacts')].pop();"
                   " return {last: all[all.length-1] === rows.parentElement,"
                   " rowsTop: rows.getBoundingClientRect().top,"
                   " actsBottom: acts ? acts.getBoundingClientRect().bottom : -1,"
                   " actsText: acts ? (acts.parentElement.querySelector('.said')"
                   "   || {}).innerText || '' : '',"
                   " user: all.filter(e => e.__item && e.__item.kind === 'user')"
                   "   .map(e => e.querySelector('.utext').innerText.trim())};})()")
    print("  colocacion:", json.dumps(pos, ensure_ascii=True))
    checks += [
        # nada de prompt inyectado: fake_pi responde al texto limpio y la
        # burbuja del usuario no muestra instruccion oculta alguna
        ("el mensaje del usuario sale limpio",
         (pos.get("user") or [""])[-1] == "hola"),
        # la tanda cierra el turno: lo ultimo del transcripto, por debajo de
        # la barra de acciones de la respuesta que la pidio
        ("la tanda es lo ultimo del turno", pos.get("last") is True),
        ("la respuesta que la pidio es la del turno",
         ANSWER in (pos.get("actsText") or "")),
        ("las filas caen bajo la barra de acciones",
         (pos.get("actsBottom") or 0) > 0
         and pos.get("rowsTop", 0) > (pos.get("actsBottom") or 9e9)),
    ]

    # copiar la respuesta: sin sugerencias pegadas
    await js("document.querySelector('.mact.copy').click()")
    await asyncio.sleep(0.2)
    cp = await js("window.__copied || ''")
    print("  copiado:", json.dumps(cp, ensure_ascii=True))
    checks += [
        ("copiar la respuesta no arrastra las sugerencias",
         all(r not in cp for r in ROWS)),
        ("copiar si trae lo que escribio el modelo", ANSWER in cp),
    ]

    # turno nuevo: la tanda anterior se queda bajo su respuesta, tenues y sin
    # pulsar; cada turno pide la suya
    await send_turn(js, "siguiente")
    old = await js("(() => {"
                   " const t = [...document.querySelectorAll('.suggests.src')];"
                   " return {n: t.length, cls: t.map(e => e.className)};})()")
    print("  tandas:", json.dumps(old, ensure_ascii=True))
    checks.append(("la tanda anterior queda gastada (visible, sin pulsar)",
                   old["n"] == 1 and "spent" in (old["cls"][0] or "")))
    await settle(js)
    checks.append(("el turno nuevo trae su propia tanda",
                   await until(js, "document.querySelectorAll"
                                   "('.suggests.src').length === 2", 10)
                   and len(calls(log)) == 2))

    # clic en una fila: ese mensaje se envia tal cual, y su turno pide las suyas
    await js("[...document.querySelectorAll('.suggests.src')].pop()"
             ".querySelector('.sug').click()")
    sent = await until(js, "state.running === true", 8)
    bubble = await js("(() => {"
                      " const u = [...feed.querySelectorAll('.turn')]"
                      "   .filter(e => e.__item && e.__item.kind === 'user');"
                      " return u[u.length-1].querySelector('.utext')"
                      ".innerText.trim();})()")
    print("  burbuja:", json.dumps(bubble, ensure_ascii=True))
    checks += [
        ("clic en una sugerencia: el mensaje vuela", sent is True),
        ("el mensaje enviado es la sugerencia exacta", bubble == ROWS[0]),
    ]
    await settle(js)
    checks.append(("la respuesta nueva tiene su tanda",
                   await until(js, "document.querySelectorAll"
                                   "('.suggests.src').length === 3", 10)))
    spent_all = await js("[...document.querySelectorAll('.suggests.src')]"
                         ".map(e => e.className)")
    checks.append(("solo la ultima tanda esta activa",
                   sum("spent" in c for c in spent_all) == 2))

    # el caso que rompió el diseno viejo: el usuario pega un <hint:> en el
    # texto. Ahora la respuesta NO se parsea: las filas salen del modelo de
    # todos modos y el marcador queda oculto en la prosa
    await send_turn(js, "pega <hint: x> en el chat")
    await settle(js)
    got4 = await until(js, "document.querySelectorAll('.suggests.src')"
                          ".length === 4", 10)
    last = await js("(() => {"
                    " const t = [...feed.querySelectorAll('.suggests.src')];"
                    " const g = t[t.length-1];"
                    " const saids = [...feed.querySelectorAll('.said')];"
                    " return {n: t.length,"
                    " rows: [...g.querySelectorAll('.stext')].map(e => e.textContent),"
                    " said: saids.length ? saids[saids.length-1].innerText : ''};})()")
    print("  marcador en prosa:", json.dumps(last, ensure_ascii=True))
    checks += [
        ("un <hint:> en la prosa no crea filas: manda el modelo",
         got4 is True and last["rows"] == ROWS),
        ("y el marcador no se ve en la respuesta",
         "<hint" not in last["said"] and "Hecho" in last["said"]),
    ]
    return len(calls(log))


async def phase_sin_endpoint(p, js, checks, proj, log, before):
    await p.go()
    await js("setLang('es')")
    await js("send({type:'open_project', path:%s})"
                 % json.dumps(proj.path))
    assert await until(js, "state.cwd !== null", 8), "no abrio el proyecto"
    await until(js, "state.modelProvider !== null", 8)
    await js("setSuggest(true);")
    checks += [
        ("sin baseUrl, el puente dice que no puede sugerir",
         await js("state.canSuggest") is False),
    ]
    sheet = await js("paintSheet('functions'); (() => {"
                     " const c = [...document.querySelectorAll"
                     "('#sheetBody .fcard')]"
                     "   .find(x => /Sugerencias/.test(x.textContent));"
                     " if(!c) return null;"
                     " const sw = c.querySelector('.sw');"
                     " const small = c.querySelector('.flbl small');"
                     " return {dis: sw.disabled, op: getComputedStyle(sw).opacity,"
                     "  checked: sw.getAttribute('aria-checked'),"
                     "  note: small ? small.textContent : ''};})()")
    print("  sin endpoint:", json.dumps(sheet, ensure_ascii=True))
    checks += [
        ("sin baseUrl: el interruptor sale apagado",
         bool(sheet) and sheet["dis"] is True),
        ("sin baseUrl: se dice el motivo",
         bool(sheet) and "URL propia" in sheet["note"]),
        ("sin baseUrl: el interruptor se ve atenuado",
         bool(sheet) and float(sheet["op"] or 1) < 0.7),
        ("sin baseUrl: el interruptor no finge estar activo",
         bool(sheet) and sheet["checked"] == "false"),
    ]
    # y aunque el flag viaje en el prompt, no se dispara nada: no hay a quien
    # escribirle, y el aro de carga no debe quedarse encendido
    await send_turn(js, "sin endpoint")
    await settle(js)
    await asyncio.sleep(0.5)
    checks += [
        ("sin endpoint: no sale aro de carga",
         await js("state.suggesting") is False
         and await js("document.querySelectorAll('.suggests.skel').length") == 0),
        ("sin endpoint: ni una llamada extra al modelo",
         len(calls(log)) == before),
        ("sin endpoint: no salen filas",
         await js("document.querySelectorAll('.suggests.src').length") == 0),
    ]


async def main():
    checks = []
    tmp = Path(os.environ.get("TEMP", "."))
    log = tmp / "pi-suggest-calls.jsonl"
    if log.exists():
        log.unlink()
    srv, port = start_model(log)
    with Bridge(extra={"PI_MODELS_JSON": write_models(
            tmp / "pi-suggest-models.json",
            "http://127.0.0.1:%d/v1" % port)}) as b1, \
            FakeProject("proj-suggest") as proj1:
        async with Page(port=9380) as p:
            n = await phase_with_endpoint(p, p.js, checks, proj1, log)
            problems = [x for x in p.problems if "favicon" not in x[1]]
            checks.append(("sin fallos en consola", not problems))
            if problems:
                print(problems[:4])
    # segundo puente: el mismo provider sin baseUrl. Ahi no hay a quien
    # pedirle las sugerencias; se apaga el interruptor y no sale ni una
    # llamada, en vez de fallar en silencio
    with Bridge(state=str(tmp / "pi-suggest-state2.json"), extra={
            "PI_MODELS_JSON": write_models(tmp / "pi-suggest-models2.json")}
            ) as b2, FakeProject("proj-suggest2") as proj2:
        async with Page(port=9380) as p2:
            await phase_sin_endpoint(p2, p2.js, checks, proj2, log, n)
    srv.shutdown()
    return checks


raise SystemExit(report(asyncio.run(main())))
