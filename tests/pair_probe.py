"""Conectar dispositivo: QR con codigo de un solo uso y aprobacion del PC.

- unidad: is_local_client solo acepta este PC, y nunca detras de un proxy
  (con proxy todo cliente llega como 127.0.0.1); device_name;
- HTTP: /api/pair y /api/pair/new solo desde este PC; los enlaces del QR
  llevan ?pair=codigo y NUNCA el token;
- flujo: sin pestana en el PC no hay a quien preguntar (409); codigo malo,
  403; el bueno abre la solicitud, avisa al PC con la cifra, y se gasta
  (segundo uso, 403); aprobar entrega el token, denegar no; sin respuesta
  caduca;
- pagina del PC: tarjeta, vista con flecha atras, QR con el enlace de
  emparejar, aviso en caja con icono; una solicitud abre el dialogo con la
  cifra, Permitir aprueba, y la vista pasa a un codigo nuevo;
- pagina del movil (?pair=): el telon se queda respirando con "Esperando
  aprobacion"; con un codigo gastado, el error.
"""
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

import websockets

from harness import (ROOT, Bridge, FakeProject, Page, PORT, TOKEN, WS_URL,
                     report)

sys.path.insert(0, str(ROOT))
import pi_web_bridge as B          # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:%d" % PORT


def call(path, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    h = dict(headers or {})
    if data is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=h,
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            raw = r.read()
            st = r.status
    except urllib.error.HTTPError as e:
        raw, st = e.read(), e.code
    try:
        return st, json.loads(raw)
    except ValueError:
        return st, raw


def new_code():
    st, d = call("/api/pair/new?token=" + TOKEN, "POST")
    url = d["links"][0]["url"] if st == 200 and d.get("links") else ""
    return url.split("?pair=")[-1] if "?pair=" in url else "", d


async def recv_type(ws, kind, timeout=5):
    end = asyncio.get_event_loop().time() + timeout
    while True:
        left = end - asyncio.get_event_loop().time()
        if left <= 0:
            return None
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), left))
        except asyncio.TimeoutError:
            return None
        if m.get("type") == kind:
            return m


def unit():
    loc = B.is_local_client
    ua = ("Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36")
    return [
        ("loopback es este PC", loc("127.0.0.1", {}) and loc("::1", {})),
        ("una IP ajena no", not loc("8.8.8.8", {})),
        ("sin host no", not loc("", {})),
        ("detras de un proxy no, aunque llegue como loopback",
         not loc("127.0.0.1", {"x-forwarded-for": "100.1.2.3"})
         and not loc("127.0.0.1", {"tailscale-user-login": "x"})),
        ("el aparato se nombra por su User-Agent",
         B.device_name(ua) == "Android · Chrome"),
    ]


async def flow():
    """Solo HTTP + WebSocket: la logica de seguridad del puente."""
    checks = []
    st, d = call("/api/pair?token=" + TOKEN)
    bad = call("/api/pair?token=otro")[0]
    prox = call("/api/pair?token=" + TOKEN,
                headers={"X-Forwarded-For": "100.1.2.3"})[0]
    newbad = call("/api/pair/new?token=otro", "POST")[0]
    newprox = call("/api/pair/new?token=" + TOKEN, "POST",
                   headers={"X-Forwarded-For": "100.1.2.3"})[0]
    code, nd = new_code()
    urls = [l["url"] for l in nd.get("links") or []]
    lib = call("/vendor/qrcode/qrcode.js")
    print("  api=%s malo=%s proxy=%s new: malo=%s proxy=%s urls=%s"
          % (st, bad, prox, newbad, newprox, urls))
    checks += [
        ("desde este PC, permiso para el QR", st == 200 and d.get("local")),
        ("token malo o proxy: 403 (ver y generar)",
         bad == prox == newbad == newprox == 403),
        ("el QR lleva ?pair= y NUNCA el token",
         all("?pair=" in u and TOKEN not in u and "token=" not in u
             for u in urls)),
        ("codigo largo (no se adivina)", len(code) >= 20 or not urls),
        ("la libreria del QR se sirve en local",
         lib[0] == 200 and b"qrcode" in lib[1]),
    ]

    # sin pestana del PC abierta: no hay quien apruebe
    code, _ = new_code()
    nohost = call("/api/pair/request", "POST", {"code": code})[0]
    async with websockets.connect(WS_URL) as ws:
        await ws.recv()                                  # snapshot
        code, _ = new_code()
        wrong = call("/api/pair/request", "POST", {"code": "x" + code})[0]
        st, rq = call("/api/pair/request", "POST", {"code": code})
        ask = await recv_type(ws, "pair_ask")
        again = call("/api/pair/request", "POST", {"code": code})[0]
        await ws.send(json.dumps({"type": "pair_answer", "id": rq.get("id"),
                                  "ok": True}))
        ok = call("/api/pair/wait?id=" + rq.get("id", ""))[1]
        done = await recv_type(ws, "pair_done")

        code, _ = new_code()
        _, rq2 = call("/api/pair/request", "POST", {"code": code})
        await recv_type(ws, "pair_ask")
        await ws.send(json.dumps({"type": "pair_answer", "id": rq2.get("id"),
                                  "ok": False}))
        no = call("/api/pair/wait?id=" + rq2.get("id", ""))[1]
    print("  sin PC=%s malo=%s pide=%s aviso=%s reuso=%s aprobado=%s "
          "denegado=%s" % (nohost, wrong, st, bool(ask), again,
                           ok.get("status"), no))
    checks += [
        ("sin pestana en el PC: 409", nohost == 409),
        ("codigo malo: 403", wrong == 403),
        ("el bueno abre la solicitud con su cifra", st == 200
         and len(rq.get("digits", "")) == 4),
        ("el PC recibe la solicitud con la MISMA cifra y la IP",
         bool(ask) and ask.get("digits") == rq.get("digits")
         and ask.get("ip")),
        ("el codigo se gasta: segundo uso, 403", again == 403),
        ("aprobar entrega el token", ok.get("status") == "approved"
         and ok.get("token") == TOKEN),
        ("y el PC lo sabe (pair_done)", bool(done)
         and done.get("status") == "approved"),
        ("denegar no entrega nada", no.get("status") == "denied"
         and "token" not in no),
        ("un id inventado no da nada",
         call("/api/pair/wait?id=inventado")[1].get("status") == "expired"),
    ]
    return checks


async def expiry():
    """Sin respuesta del PC, la solicitud caduca (PI_PAIR_WAIT=2)."""
    async with websockets.connect(WS_URL) as ws:
        await ws.recv()
        code, _ = new_code()
        _, rq = call("/api/pair/request", "POST", {"code": code})
        d = call("/api/pair/wait?id=" + rq.get("id", ""))[1]
        done = await recv_type(ws, "pair_done", 5)
    print("  caducidad: %s, aviso=%s" % (d, done))
    return [("sin respuesta, caduca y no hay token",
             d.get("status") == "expired" and "token" not in d),
            ("y el dialogo del PC se cierra (pair_done expired)",
             bool(done) and done.get("status") == "expired")]


async def pages():
    checks = []
    async with Page(port=9461) as p:
        js = p.js
        await p.go()
        await js("setLang('es')")
        for _ in range(40):
            if await js("PAIR === true"):
                break
            await asyncio.sleep(0.1)
        await js("$('#sheet').classList.add('open'); paintSheet('root')")
        await asyncio.sleep(0.2)
        card = await js("[...document.querySelectorAll('#sheetBody .pick')]"
                        ".some(b => b.textContent.includes("
                        "'Conectar dispositivo'))")
        await js("goPage('pair')")
        view = None
        for _ in range(50):
            view = await js("""(() => {
              const box = document.querySelector('.pairqr');
              const svg = box && box.querySelector('svg');
              const path = svg && svg.querySelector('path');
              const w = document.querySelector('.pairwarn');
              const wi = w && w.querySelector('.i');
              const cs = w ? getComputedStyle(w) : null;
              const url = document.querySelector('.pairurl');
              return {title: $('#sheetTitle').textContent,
                      back: !$('#sheetBack').hidden,
                      url: box ? box.dataset.url : null,
                      d: path ? path.getAttribute('d').length : 0,
                      bg: svg ? getComputedStyle(svg).backgroundColor : '',
                      w: svg ? svg.getBoundingClientRect().width : 0,
                      text: url ? url.textContent : '',
                      mono: url ? getComputedStyle(url).fontFamily : '',
                      warn: w ? w.textContent : '',
                      wicon: !!wi && wi.getBoundingClientRect().left
                               < w.querySelector('span').getBoundingClientRect().left,
                      wflex: cs ? cs.display + '/' + cs.alignItems : '',
                      wrad: cs ? cs.borderTopLeftRadius : '',
                      wcol: cs ? cs.color : '',
                      icol: wi ? getComputedStyle(wi).color : '',
                      links: pairLinks};
            })()""")
            if view["d"]:
                break
            await asyncio.sleep(0.15)
        print("  vista:", json.dumps({k: v for k, v in view.items()
                                      if k != "links"}, ensure_ascii=False))
        if os.environ.get("PI_SHOT"):
            await p.shot(os.environ["PI_SHOT"])
        links = view["links"] or []
        checks += [
            ("la tarjeta sale en Ajustes en este PC", card is True),
            ("abre su vista, con titulo y flecha atras",
             view["title"] == "Conectar dispositivo" and view["back"]),
        ]
        if links:
            checks += [
                ("el QR es el enlace de emparejar, sin token",
                 view["url"] == links[0]["url"] == view["text"]
                 and "?pair=" in view["url"] and TOKEN not in view["url"]),
                ("el QR se pinta: SVG con modulos, negro sobre blanco",
                 view["d"] > 500 and view["w"] > 150
                 and view["bg"] == "rgb(255, 255, 255)"),
                ("el enlace en mono (es un dato)", "Plex Mono" in view["mono"]),
            ]
        checks += [
            ("aviso en caja: el texto pedido",
             view["warn"].startswith("Pi remote se abrir")
             and "ejecutar comandos" in view["warn"]),
            ("icono a la izquierda, centrado en vertical",
             view["wicon"] and view["wflex"] == "flex/center"),
            ("esquinas redondeadas", view["wrad"] not in ("", "0px")),
            ("icono y texto en el mismo gris",
             view["icol"] == view["wcol"]),
        ]

        # una solicitud desde "el movil": el PC ve el dialogo con la cifra
        if links:
            code = view["url"].split("?pair=")[-1]
            st, rq = await asyncio.to_thread(
                call, "/api/pair/request", "POST", {"code": code})
            await asyncio.sleep(0.6)
            dlg = await js("""[$('#modal').classList.contains('open'),
                              $('#modalTitle').textContent,
                              (document.querySelector('#modalBody .pairdig')
                               || {}).textContent,
                              $('#modalOk').textContent]""")
            if os.environ.get("PI_SHOT_ASK"):
                await p.shot(os.environ["PI_SHOT_ASK"])
            # Denegar: la vista sigue abierta, con un codigo nuevo
            waiter = asyncio.create_task(asyncio.to_thread(
                call, "/api/pair/wait?id=" + rq.get("id", "")))
            await js("$('#modalNo').click()")
            got = (await waiter)[1]
            fresh = None
            for _ in range(30):
                await asyncio.sleep(0.2)
                fresh = await js("(() => { const b = document.querySelector("
                                 "'.pairqr'); return b && b.querySelector("
                                 "'svg') ? b.dataset.url : null; })()")
                if fresh and fresh != view["url"]:
                    break
            still = await js("$('#sheet').classList.contains('open')")
            print("  dialogo=%s  denegar=%s  sigue abierta=%s  codigo nuevo=%s"
                  % (dlg, got.get("status"), still, fresh != view["url"]))
            checks += [
                ("el PC abre el dialogo con la cifra del movil",
                 dlg[0] is True and dlg[1] == "¿Conectar un dispositivo?"
                 and dlg[2] == rq.get("digits") and dlg[3] == "Permitir"),
                ("Denegar no da token", got.get("status") == "denied"
                 and "token" not in got),
                ("denegado: la vista sigue, con un codigo nuevo",
                 still is True and bool(fresh) and fresh != view["url"]),
            ]

            # Permitir: el movil recibe el token y la hoja del QR se cierra
            code = fresh.split("?pair=")[-1] if fresh else ""
            st, rq = await asyncio.to_thread(
                call, "/api/pair/request", "POST", {"code": code})
            await asyncio.sleep(0.6)
            waiter = asyncio.create_task(asyncio.to_thread(
                call, "/api/pair/wait?id=" + rq.get("id", "")))
            await js("$('#modalOk').click()")
            got = (await waiter)[1]
            await asyncio.sleep(0.8)
            after = await js("""[$('#sheet').classList.contains('open'),
                [...document.querySelectorAll('#feed .note')]
                  .some(n => n.textContent.includes('Dispositivo conectado'))]""")
            print("  permitir=%s  hoja abierta=%s  aviso=%s"
                  % (got.get("status"), after[0], after[1]))
            checks += [
                ("Permitir aprueba y el movil recibe el token",
                 got.get("status") == "approved" and got.get("token") == TOKEN),
                ("conectado: la hoja del QR se cierra sola", after[0] is False),
                ("y avisa: Dispositivo conectado", after[1] is True),
            ]

        await js("$('#sheet').classList.add('open'); PAIR = false;"
                 " paintSheet('root')")
        await asyncio.sleep(0.1)
        hidden = await js("![...document.querySelectorAll('#sheetBody .pick')]"
                          ".some(b => b.textContent.includes("
                          "'Conectar dispositivo'))")
        checks += [("sin permiso del puente, no hay tarjeta", hidden is True),
                   ("sin errores de consola (PC)", not p.problems)]

    # el movil, camino feliz: espera con la cifra, el PC aprueba, entra
    async with websockets.connect(WS_URL) as pc, Page(port=9463) as m:
        await pc.recv()
        code, _ = await asyncio.to_thread(new_code)
        await m.go("http://127.0.0.1:%d/?pair=%s" % (PORT, code), settle=0.5)
        ask = await recv_type(pc, "pair_ask", 8)
        await asyncio.sleep(0.5)
        wait = await m.js("""[$('#curtain').classList.contains('pairing'),
                             $('#curtain').classList.contains('gone'),
                             ($('#curtsub') || {}).textContent,
                             (document.querySelector('#curtsub .cdig')
                              || {}).textContent]""")
        if os.environ.get("PI_SHOT_WAIT"):
            await m.shot(os.environ["PI_SHOT_WAIT"])
        await pc.send(json.dumps({"type": "pair_answer",
                                  "id": (ask or {}).get("id"), "ok": True}))
        inside = None
        for _ in range(40):
            await asyncio.sleep(0.25)
            inside = await m.js("""[location.search,
                (() => { try { return localStorage.getItem('pi.token'); }
                         catch(e){ return null; } })(),
                typeof ws !== 'undefined' && !!ws && ws.readyState === 1]""")
            if isinstance(inside, list) and inside[2] is True:
                break
        print("  movil esperando=%s  dentro=%s" % (wait, inside))
        checks += [
            ("el movil espera en el telon con su cifra",
             wait[0] is True and wait[1] is False
             and "aprobaci" in (wait[2] or "").lower()
             and bool(ask) and wait[3] == ask.get("digits")),
            ("aprobado: guarda el token, quita el codigo de la URL y conecta",
             isinstance(inside, list) and inside[0] == ""
             and inside[1] == TOKEN and inside[2] is True),
            ("sin errores de consola (movil)", not m.problems),
        ]

    # el movil: llega con un codigo gastado
    async with Page(port=9462) as m:
        await m.go("http://127.0.0.1:%d/?pair=gastado" % PORT, settle=3)
        await m.js("setLang('es')")
        st = await m.js("""[$('#curtain').classList.contains('pairing'),
                           $('#curtain').classList.contains('gone'),
                           $('#curtain').classList.contains('pairfail'),
                           ($('#curtsub') || {}).textContent]""")
        print("  movil (codigo gastado):", st)
        if os.environ.get("PI_SHOT_PHONE"):
            await m.shot(os.environ["PI_SHOT_PHONE"])
        checks += [
            ("el movil se queda en el telon, sin entrar",
             st[0] is True and st[1] is False),
            ("con codigo gastado, el error en el telon",
             st[2] is True and "ya se us" in (st[3] or "")),
        ]
    return checks


async def main():
    checks = unit()
    with Bridge(), FakeProject():
        checks += await flow()
        checks += await pages()
    with Bridge(extra={"PI_PAIR_WAIT": "2"}), FakeProject():
        checks += await expiry()
    return checks


raise SystemExit(report(asyncio.run(main())))
