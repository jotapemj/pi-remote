"""Aviso de version nueva (modelo Immich: solo avisa). El puente consulta la
ultima release al arrancar y cada hora; si es mas nueva que la que corre, la
publica en el estado. El cliente pinta un punto ambar en el engranaje hasta
que se leen las notas de esa version, y una tarjeta en el menu que abre las
notas con los pasos para actualizar. Un servidor local imita la API de
GitHub; PI_UPDATE_CHECK=off apaga la consulta.
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from harness import Bridge, Page, report

RELEASE = {"tag_name": "v9.9.9", "name": "Big release",
           "html_url": "https://github.com/x/pi-remote/releases/tag/v9.9.9",
           # escrito a columna fija, como las notas reales: las lineas de un
           # parrafo o de una vinyeta se unen al pintar
           "body": "## Interface\r\n\r\n- **New thing.** Does stuff\r\n"
                   "  across two lines.\r\n- Second item.\r\n\r\n"
                   "Plain paragraph\r\nwrapped too.\r\n",
           "published_at": "2026-10-01T10:00:00Z"}
SERVE = {"rel": RELEASE}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps(SERVE["rel"]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def backend(url):
    import pi_web_bridge as B
    checks = []
    old_url, old_ver = B.UPDATE_URL, B.VERSION
    B.UPDATE_URL = url
    try:
        checks += [
            ("version a tupla, tolerante",
             B.ver_tuple("v0.95.0") == (0, 95, 0)
             and B.ver_tuple("1.2") == (1, 2, 0)
             and B.ver_tuple("v0.100.3-beta") == (0, 100, 3)),
            ("0.100 es mas nueva que 0.99 (no comparar texto)",
             B.ver_tuple("0.100.0") > B.ver_tuple("0.99.9")),
        ]
        B.VERSION = "0.95.0"
        up = B.check_update()
        checks += [
            ("release mas nueva: se avisa con version, nombre y enlace",
             up and up["version"] == "9.9.9" and up["name"] == "Big release"
             and up["url"].endswith("v9.9.9")),
            ("las notas llegan sin \\r", up and "\r" not in up["notes"]),
        ]
        B.VERSION = "9.9.9"
        checks.append(("la misma version: nada que avisar",
                       B.check_update() is None))
        B.VERSION = "10.0.0"
        checks.append(("corriendo una mas nueva (desarrollo): nada",
                       B.check_update() is None))
    finally:
        B.UPDATE_URL, B.VERSION = old_url, old_ver
    return checks


async def ui(url):
    checks = []
    # el harness la apaga por defecto (sin red): aqui se enciende contra el fake
    with Bridge(extra={"PI_UPDATE_URL": url, "PI_UPDATE_CHECK": "on"}):
        async with Page(port=9452) as p:
            js = p.js
            await p.go()
            await asyncio.sleep(0.8)
            await js("setLang('en'); localStorage.removeItem('pi.seenUpdate')")
            st = await js("""(() => ({up: state.update && state.update.version,
              dot: (paint(), $('#menuBtn').classList.contains('upd')),
              dotBg: getComputedStyle($('#menuBtn'), '::after').backgroundColor}))()""")
            await js("menuSheet()")
            await asyncio.sleep(0.5)
            card = await js("""(() => { const c = document.querySelector(
              '#sheetBody .updcard'); return c ? c.textContent : null; })()""")
            # sitio: justo tras la linea que separa los grupos, sobre Help
            place = await js("""(() => { const c = document.querySelector(
              '#sheetBody .updcard');
              return [c.previousElementSibling.className,
                      c.nextElementSibling.textContent]; })()""")
            await js("document.querySelector('#sheetBody .updcard').click()")
            await asyncio.sleep(0.4)
            dlg = await js("""(() => ({title: $('#modalTitle').textContent,
              h2: (document.querySelector('#modalBody .updnotes h4') || {})
                .textContent,
              how: !!document.querySelector('#modalBody .updhow pre'),
              cmd: (document.querySelector('#modalBody .updhow pre') || {})
                .textContent,
              link: (document.querySelector('#modalBody .updlink') || {}).href,
              lis: [...document.querySelectorAll('#modalBody .updnotes li')]
                .map(l => l.textContent),
              para: [...document.querySelectorAll('#modalBody .updnotes p')]
                .map(x => x.textContent),
              dot: $('#menuBtn').classList.contains('upd'),
              seen: localStorage.getItem('pi.seenUpdate')}))()""")
            await js("closeModal(); menuSheet()")
            await asyncio.sleep(0.4)
            again = await js("!!document.querySelector('#sheetBody .updcard')")
            print("  estado=%s tarjeta=%r dialogo=%s sigue=%s"
                  % (st, card, dlg, again))
            checks += [
                ("el puente publica la version nueva en el estado",
                 st["up"] == "9.9.9"),
                ("punto en el engranaje, sin leer", st["dot"] is True),
                ("el punto es color acento",
                 st["dotBg"] not in ("rgba(0, 0, 0, 0)", "")),
                ("tarjeta en el menu: version nueva, ver notas",
                 card and "New version available" in card
                 and "See release notes" in card),
                ("la tarjeta va tras la linea y sobre Help",
                 place[0] == "sdiv" and place[1].startswith("Help")),
                ("el dialogo lleva la version y las notas renderizadas",
                 dlg["title"] == "pi remote v9.9.9" and dlg["h2"] == "Interface"),
                ("y, aparte, los pasos para actualizar",
                 dlg["how"] and "git pull" in dlg["cmd"]
                 and "pip install -r requirements.txt" in dlg["cmd"]),
                ("las lineas partidas de una vinyeta se unen",
                 dlg["lis"] == ["New thing. Does stuff across two lines.",
                                "Second item."]),
                ("y las de un parrafo tambien",
                 "Plain paragraph wrapped too." in dlg["para"]),
                ("con enlace a la release en GitHub",
                 (dlg["link"] or "").endswith("/releases/tag/v9.9.9")),
                ("leidas las notas, el punto se va", dlg["dot"] is False
                 and dlg["seen"] == "9.9.9"),
                ("la tarjeta sigue para releerlas", again),
            ]
            # otra version mas nueva: el punto vuelve
            dot2 = await js("""(() => { state.update = Object.assign({},
              state.update, {version: '9.9.10'}); paint();
              return $('#menuBtn').classList.contains('upd'); })()""")
            checks.append(("con otra version mas nueva el punto vuelve", dot2))

    # apagado: ni se consulta ni se avisa
    with Bridge(extra={"PI_UPDATE_URL": url, "PI_UPDATE_CHECK": "off"}):
        async with Page(port=9453) as p:
            await p.go()
            await asyncio.sleep(1.0)
            off = await p.js("state.update")
            checks.append(("PI_UPDATE_CHECK=off: no hay aviso", off is None))
    return checks


async def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/latest" % server.server_address[1]
    try:
        return backend(url) + await ui(url)
    finally:
        server.shutdown()


raise SystemExit(report(asyncio.run(main())))
