"""Resumen al parar (opcion A): con la funcion activa, parar un turno pensante
manda {abort, summary}. El puente ABORTA el turno (lo interrumpe de verdad) y,
al asentarse, pide el resumen DIRECTO al modelo local (endpoint OpenAI-compatible,
thinking off), NO via pi: la sesion no se ensucia y el turno no hereda el xhigh
que lo pondria a pensar. El boton queda en aro (summing, guiado por
state.summarizing) desde el abort hasta que llega el resumen, que se pinta como
burbuja de asistente transitoria. Apagada, parar es un abort normal, sin resumen.
El modelo es un mini servidor HTTP que devuelve un resumen fijo y registra las
peticiones (para comprobar que van sin pensar).
"""
import asyncio
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from harness import Bridge, FakeProject, Page, report


async def until(p, expr, timeout=8.0, step=0.1):
    for _ in range(int(timeout / step)):
        if await p.js(expr):
            return True
        await asyncio.sleep(step)
    return False


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        with open(self.server.logpath, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(body) + "\n")
        time.sleep(0.4)          # latencia real del modelo: el aro se ve subir
        resp = json.dumps({"choices": [{"message": {
            "content": self.server.summary}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *a):
        pass


def reqs(path):
    p = Path(path)
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] \
        if p.exists() else []


async def think_start(p):
    """Arranca un turno pensante (fake_pi: 'stopme') y espera a que piense."""
    await p.js("feed.innerHTML=''; nodes.clear();"
               " send({type:'prompt', message:'stopme'})")
    run = await until(p, "state.running === true")
    think = await until(p, "!!document.querySelector('.think')")
    return run and think


async def main():
    tmp = Path(os.environ.get("TEMP", "."))
    log = tmp / "pi-stopsum-log.txt"
    models = tmp / "pi-stopsum-models.json"
    if log.exists():
        log.unlink()

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.summary = "Vale, paro. Estaba revisando el puente."
    srv.logpath = str(log)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    models.write_text(json.dumps({"providers": {"local": {
        "baseUrl": "http://127.0.0.1:%d" % port, "apiKey": "k"}}}),
        encoding="utf-8")

    checks = []
    with Bridge(extra={"PI_MODELS_JSON": str(models)}), FakeProject() as proj:
        async with Page(port=9331) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")
            await js("send({type:'open_project', path:%s})"
                     % json.dumps(proj.path))
            await asyncio.sleep(1.5)

            # --- OFF: parar sin la funcion -> abort, ningun resumen ---
            off_ok = await think_start(p)
            await js("stopsum = false; $('#send').click()")   # abort normal
            await until(p, "state.running === false")
            await asyncio.sleep(0.3)
            off_sum = await js("[...document.querySelectorAll('.said')]"
                               ".some(e => e.textContent.includes('Estaba'))")
            off_reqs = len(reqs(log))
            print("  OFF: penso=%s resumen=%s peticiones=%s"
                  % (off_ok, off_sum, off_reqs))
            checks += [
                ("el turno pensante arranca", off_ok),
                ("apagado, parar no genera resumen", off_sum is False),
                ("apagado, no se pide nada al modelo", off_reqs == 0),
            ]

            # --- ON: parar con la funcion -> abort + resumen directo al modelo -
            on_ok = await think_start(p)
            before = await js("document.querySelectorAll('.blk-you').length")
            await js("stopsum = true; $('#send').click()")
            # el aro se marca al abortar (state.summarizing del puente)
            ring = await until(p, "$('#send').classList.contains('summing')",
                               timeout=3)
            got = await until(p, "[...document.querySelectorAll('.said')]"
                              ".some(e => e.textContent.includes('Estaba'))")
            ring_off = await until(p, "!$('#send')"
                                   ".classList.contains('summing')", timeout=5)
            await asyncio.sleep(0.2)
            # la generacion original se corto: nunca llego su 'Listo.'
            finished = await js("[...document.querySelectorAll('.said')]"
                                ".some(e => e.textContent.trim() === 'Listo.')")
            txt = await js("[...document.querySelectorAll('.said')]"
                           ".map(e => e.textContent)"
                           ".filter(t => t.includes('Estaba')).pop() || null")
            after = await js("document.querySelectorAll('.blk-you').length")
            got_reqs = reqs(log)
            asked = got_reqs[-1] if got_reqs else {}
            instr = ((asked.get("messages") or [{}])[0].get("content", "")
                     if asked else "")
            no_think = ((asked.get("chat_template_kwargs") or {})
                        .get("enable_thinking"))
            print("  ON: penso=%s aro=%s->%s corto=%s users %s->%s peticiones=%s"
                  " think=%s texto=%r"
                  % (on_ok, ring, ring_off, not finished, before, after,
                     len(got_reqs), no_think, txt))
            checks += [
                ("el turno pensante arranca (on)", on_ok),
                ("el boton entra en aro al parar", ring),
                ("la generacion se interrumpe (no termina)", not finished),
                ("aparece la respuesta al parar", got),
                ("la respuesta trae confirmacion + estaba",
                 bool(txt) and "Vale, paro" in txt
                 and "Estaba revisando" in txt),
                ("el resumen se pide al modelo local (directo)",
                 len(got_reqs) == 1),
                ("la peticion va SIN pensar (enable_thinking False)",
                 no_think is False),
                ("la instruccion es la del resumen al parar",
                 "You were just interrupted" in instr),
                ("el aro se quita al terminar", ring_off),
                ("el resumen no anade burbuja de usuario", after == before),
            ]

            checks.append(("sin errores de consola", not p.problems))

    srv.shutdown()
    return checks


raise SystemExit(report(asyncio.run(main())))
