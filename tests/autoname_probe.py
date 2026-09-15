"""Autonombre: el primer prompt de una sesion sin nombre pide al modelo local
(un endpoint OpenAI-compatible) un titulo en el idioma elegido. Un solo
intento por sesion: si el endpoint falla, la sesion queda sin nombre y la
mascara del cliente lo pinta. Aqui el modelo es un mini servidor HTTP que
devuelve un titulo fijo y registra las peticiones."""
import asyncio
import json
import os
import threading
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
            fh.write(body["messages"][0]["content"] + "\n---\n")
        resp = json.dumps({"choices": [{"message": {
            "content": self.server.title}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *a):
        pass


def reqs(path):
    p = Path(path)
    return p.read_text(encoding="utf-8").splitlines() if p.exists() else []


async def main():
    tmp = Path(os.environ.get("TEMP", "."))
    log = tmp / "pi-autoname-log.txt"
    models = tmp / "pi-autoname-models.json"
    if log.exists():
        log.unlink()

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    srv.title = "Fixing the bridge"
    srv.logpath = str(log)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    models.write_text(json.dumps({"providers": {"local": {
        "baseUrl": "http://127.0.0.1:%d" % port, "apiKey": "k"}}}),
        encoding="utf-8")

    checks = []
    with Bridge(extra={"PI_MODELS_JSON": str(models)}), FakeProject() as proj:
        async with Page(port=9342) as p:
            js = p.js
            await p.go()
            await js("send({type:'open_project', path:%s})"
                     % json.dumps(proj.path))
            await until(p, "state.running === false")
            await asyncio.sleep(1.0)

            # --- sesion nueva sin nombre: la mascara lo pinta (tras la
            # gracia del titulo) ---
            await js("send({type:'new_session'})")
            await until(p, "state.sessionName == null")
            masked = await until(p, "'Untitled' in $('#title').textContent",
                                 timeout=6)
            checks.append(("una sesion sin nombre muestra la mascara",
                           masked is True))

            # --- primer prompt con autoname: pide el titulo y lo aplica ---
            await js("send({type:'prompt', message:'fix the bridge please',"
                     " autoname:true, lang:'en'})")
            await until(p, "state.running === false")
            await asyncio.sleep(1.0)
            name = await js("state.sessionName")
            got = reqs(log)
            checks += [
                ("el puente pide el titulo al modelo local", len(got) >= 1),
                ("la peticion lleva el texto literal del usuario",
                 any("fix the bridge" in l for l in got)),
                ("la instruccion pide el idioma elegido",
                 any("in English" in l for l in got)),
                ("la sesion queda nombrada con el titulo del modelo",
                 name == "Fixing the bridge"),
            ]

            # --- un solo intento: nombrada, ya no se vuelve a pedir ---
            n0 = len(got)
            await js("send({type:'prompt', message:'second prompt',"
                     " autoname:true, lang:'en'})")
            await until(p, "state.running === false")
            await asyncio.sleep(0.5)
            checks.append(("sin segundo intento en sesion ya nombrada",
                           len(reqs(log)) == n0))

    # --- fallo del endpoint: el prompt viaja igual, la sesion queda sin nombre
    dead = tmp / "pi-autoname-dead.json"
    dead.write_text(json.dumps({"providers": {"local": {
        "baseUrl": "http://127.0.0.1:1", "apiKey": "k"}}}), encoding="utf-8")
    with Bridge(extra={"PI_MODELS_JSON": str(dead)}), FakeProject() as proj:
        async with Page(port=9342) as p:
            js = p.js
            await p.go()
            await js("send({type:'open_project', path:%s})"
                     % json.dumps(proj.path))
            await until(p, "state.running === false")
            await asyncio.sleep(1.0)
            await js("send({type:'new_session'})")
            await until(p, "state.sessionName == null")
            await js("send({type:'prompt', message:'hello there',"
                     " autoname:true, lang:'es'})")
            await until(p, "state.running === false")
            # la conexion muerta tarda en morir (y el prompt viaja despues)
            sent = await until(p, "'hello there' in $('#feed').textContent",
                               timeout=15)
            name = await js("state.sessionName")
            masked = await until(p, "'Untitled' in $('#title').textContent",
                                 timeout=6)
            checks += [
                ("endpoint caido: el prompt viaja sin nombre",
                 name is None and sent is True),
                ("endpoint caido: la mascara sigue pintada",
                 masked is True),
            ]

    srv.shutdown()
    return report(checks)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
