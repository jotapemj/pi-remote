"""Store: catalogo de paquetes pi.dev. El puente parsea el HTML (no hay API
JSON), cachea 10 min por consulta, e instala/quita con `pi` (el dueño de los
ficheros). Un servidor local con fixtures replica la maquetacion real de
pi.dev; PI_PKG_CMD sustituye a `pi install|remove` para no tocar la
instalacion real."""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import (BaseHTTPRequestHandler, ThreadingHTTPServer)
from pathlib import Path
from urllib.parse import urlparse

from harness import Bridge, Page, report, PORT, TOKEN

TMP = Path(tempfile.gettempdir()) / "store_probe_tmp"
HITS = {"list": 0, "detail": 0}


def card(i, name=None, desc=None, author=None, dls=None, date=None,
         types="extension"):
    n = name or ("pkg-%02d" % i)
    return (
        '<article data-package-card="true" data-package-name="%s" '
        'data-package-search="%s x" data-package-types="%s" '
        'data-package-downloads="%s" data-package-date="%s">'
        '<h3>%s</h3>'
        '<p class="packages-desc">%s</p>'
        '<div class="packages-meta"><span>%s</span><span>%s</span>'
        '<span>%s</span></div></article>'
        % (n, n, types, dls or "1k", date or "Jan 1, 2026",
           n, desc or ("Desc %s" % n), author or "alice",
           dls or "1.2k", date or "Jan 1, 2026"))


def list_html(page=1):
    # pagina de 50 como el pi.dev real: la pagina 1 trae 50 de 62
    cards = [card(0, "alpha", "First package &amp; more", "alice", "1.2k"),
             card(1, "beta", "Second one", "bob"),
             card(2, "gamma", "A prompt pack", "carla", types="prompt")]
    cards += [card(i) for i in range(3, 62)]
    total = len(cards)
    lo = (page - 1) * 50 + 1
    hi = min(page * 50, total)
    return ('<html><body><div class="packages-count">%d-%d / %d (of %d)</div>'
            % (lo, hi, total, total)) + "".join(cards[lo - 1:hi])
    + "</body></html>"


DETAIL = """<html><body>
<dl class="definition-grid detail-grid">
<dt>Package</dt><dd>alpha</dd>
<dt>Version</dt><dd>1.0.0</dd>
<dt>Published</dt><dd>Jan 1, 2026</dd>
<dt>Downloads</dt><dd>1.2k / month</dd>
<dt>Author</dt><dd>alice</dd>
<dt>License</dt><dd>MIT</dd>
<dt>Types</dt><dd>extension skill</dd>
<dt>Size</dt><dd>42 kB</dd>
<dt>Dependencies</dt><dd>none</dd>
</dl>
<details open><summary>Pi manifest JSON</summary>
<pre class="raw-data-panel">{"pi":{"extensions":["./index.ts"]}}</pre>
</details>
<div class="packages-detail-links"><a href="https://www.npmjs.com/package/alpha">npm</a><a href="https://github.com/x/alpha">repo</a></div>
<section>
<div class="rich-text packages-readme"><h1>Alpha</h1><p>Does things.</p><img src="__BASE__/logo.png" alt="logo"><img src="rel.png" alt="rel"><img src="__BASE__/page.html" alt="page"></div>
</section>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.0: cierra tras cada respuesta. Con keep-alive, el server
    # mono-hilo se quedaba con la conexion abierta y el urlopen del
    # puente bloqueaba su loop de asyncio (WS sin delivery).
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/packages":
            HITS["list"] += 1
            page = int(u.query.split("page=")[1]) if "page=" in u.query else 1
            body = list_html(page).encode()
        elif u.path == "/packages/alpha":
            HITS["detail"] += 1
            base = "http://127.0.0.1:%d" % self.server.server_address[1]
            body = DETAIL.replace("__BASE__", base).encode()
        elif u.path == "/logo.png":            # imagen del README
            HITS["img"] = HITS.get("img", 0) + 1
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", "8")
            self.end_headers()
            self.wfile.write(b"\x89PNG\r\n\x1a\n")
            return
        elif u.path == "/redir":               # salto hacia otro host
            self.send_response(302)
            self.send_header("Location", "http://localhost:%d/logo.png"
                             % self.server.server_address[1])
            self.end_headers()
            return
        elif u.path == "/page.html":           # no es imagen
            body = b"<html>nope</html>"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def seed(td):
    """Agent dir con alpha ya instalado (settings + node_modules)."""
    a = Path(td)
    (a / "npm" / "node_modules" / "alpha").mkdir(parents=True)
    (a / "settings.json").write_text(
        json.dumps({"packages": ["npm:alpha@1.0.0"]}), encoding="utf-8")


def fake_pkg_script():
    """Sustituye a `pi install|remove npm:<n>`: escribe settings.json y
    node_modules. El remove deja el residuo en node_modules a proposito:
    el probe mide la deteccion."""
    p = TMP / "fake_pkg.py"
    p.write_text(
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "action, spec = sys.argv[1], sys.argv[2]\n"
        "name = spec[4:]\n"
        "agent = Path(os.environ['PI_AGENT_DIR'])\n"
        "s = agent / 'settings.json'\n"
        "pkgs = json.loads(s.read_text()) if s.is_file() else {'packages':[]}\n"
        "if action == 'install':\n"
        "    time.sleep(0.5)\n"
        "    pkgs['packages'].append('npm:' + name)\n"
        "    (agent / 'npm' / 'node_modules' / name).mkdir(parents=True, exist_ok=True)\n"
        "elif action == 'remove':\n"
        "    pkgs['packages'] = [p for p in pkgs['packages']\n"
        "        if not p.startswith('npm:' + name)]\n"
        "(agent / 'settings.json').write_text(json.dumps(pkgs))\n",
        encoding="utf-8")
    return str(p)


def backend():
    import pi_web_bridge as B
    checks = []
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True)
    seed(str(TMP))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    B.AGENT_DIR = Path(TMP)
    B.STORE_BASE = "http://127.0.0.1:%d" % port
    B.PKG_CMD = [sys.executable, fake_pkg_script()]
    # el fake lee PI_AGENT_DIR del entorno del proceso que lo lanza
    os.environ["PI_AGENT_DIR"] = str(TMP)
    try:
        r = B.store_search("", "", "downloads", 1)
        by = {p["name"]: p for p in r["packages"]}
        checks += [
            ("la lista parsea las tarjetas de la pagina 1",
             len(r["packages"]) == 50 and "alpha" in by),
            ("los campos salen de la maquetacion",
             by["alpha"]["desc"] == "First package & more"
             and by["alpha"]["author"] == "alice"
             and by["alpha"]["downloads"] == "1.2k"
             and by["alpha"]["types"] == ["extension"]),
            ("el total sale del contador", r["total"] == 62),
            ("hasMore: 50 < 62", r["hasMore"] is True),
        ]
        # el flag instalado se calcula fresco, sin caché
        checks += [
            ("alpha sale instalado (settings.json)", by["alpha"]["installed"]),
            ("beta no lo esta", not by["beta"]["installed"]),
        ]
        hits = dict(HITS)
        B.store_search("", "", "downloads", 1)
        checks.append(("la segunda consulta no vuelve a la red",
                       HITS == hits))
        d = B.store_detail("alpha")
        checks += [
            ("el detalle trae los campos del dl",
             d["version"] == "1.0.0" and d["license"] == "MIT"
             and d["author"] == "alice" and d["size"] == "42 kB"),
            ("el manifest JSON viaja crudo", '"pi"' in d.get("manifest", "")),
            ("el readme sale del bloque rich-text",
             "<h1>Alpha</h1>" in d.get("readme", "")),
            ("los enlaces npm/repo se mapean",
             d.get("links", {}).get("repo") == "https://github.com/x/alpha"),
            ("el detalle marca instalado", d["installed"] is True),
        ]
        # ---- imagenes del README: proxy en memoria, sin residuos ----
        base = B.STORE_BASE
        urls = B.readme_img_urls(d["readme"])
        logo, page = base + "/logo.png", base + "/page.html"
        checks.append(("del README salen las imagenes absolutas, no las relativas",
                       urls == {logo, page}))
        B.readme_img_clear()
        checks.append(("una URL que no es del README no se sirve",
                       B.readme_img(logo) is None))
        B._readme_imgs.update(urls)
        checks.append(("la red local se rechaza (127.0.0.1)",
                       B.readme_img(logo) is None))
        real_host = B._public_host
        B._public_host = lambda h: h == "127.0.0.1"   # el fixture pasa
        try:
            got = B.readme_img(logo)
            checks += [
                ("la imagen se sirve desde memoria",
                 got is not None and got[0] == "image/png"
                 and got[1].startswith(b"\x89PNG")),
                ("lo que no es imagen no pasa", B.readme_img(page) is None),
            ]
            n = HITS.get("img", 0)
            B.readme_img(logo)
            checks.append(("la segunda vez sale de la cache",
                           HITS.get("img", 0) == n))
            B._readme_imgs.add(base + "/redir")
            checks.append(("una redireccion a otro host no publico se corta",
                           B.readme_img(base + "/redir") is None))
            B.readme_img_clear()
            checks += [
                ("cerrar el README vacia la cache",
                 not B._img_cache and not B._readme_imgs),
                ("y tras cerrar ya no se sirve", B.readme_img(logo) is None),
            ]
        finally:
            B._public_host = real_host
        # ---- instalados: scoped sin version, filtro y orden ----
        sfile = TMP / "settings.json"
        keep = sfile.read_text(encoding="utf-8")
        sfile.write_text(json.dumps({"packages": [
            "npm:alpha@1.0.0", "npm:@scope/ghost", "npm:@scope/pinned@2.0.0",
            "npm:gamma", "..\\local\\path"]}), encoding="utf-8")
        names = B.installed_names()
        checks += [
            ("scoped sin version no se queda en ''",
             "@scope/ghost" in names and "" not in names),
            ("scoped con version pierde solo la version",
             "@scope/pinned" in names),
            ("las rutas locales no son paquetes npm",
             names == {"alpha", "@scope/ghost", "@scope/pinned", "gamma"}),
        ]
        r = B.store_installed("", "name")
        by = {p["name"]: p for p in r["packages"]}
        checks += [
            ("instalados trae la descripcion de la tarjeta",
             by["alpha"]["desc"] == "First package & more"
             and by["gamma"]["types"] == ["prompt"]),
            ("uno que pi.dev no conoce sale igual, no se esconde",
             "@scope/ghost" in by and by["@scope/ghost"]["installed"]),
            ("orden por nombre",
             [p["name"] for p in r["packages"]]
             == ["@scope/ghost", "@scope/pinned", "alpha", "gamma"]),
        ]
        r = B.store_installed("GAM", "downloads")
        checks.append(("el texto filtra instalados (sin mayusculas)",
                       [p["name"] for p in r["packages"]] == ["gamma"]))
        sfile.write_text(keep, encoding="utf-8")
        # instalar: el fake escribe settings + node_modules
        r = B._store_run("install", "beta")
        s = json.loads((TMP / "settings.json").read_text())
        checks += [
            ("instalar beta no da error", r[0] is None),
            ("beta queda en settings.json", "npm:beta" in s["packages"]),
            ("beta queda en node_modules",
             (TMP / "npm" / "node_modules" / "beta").is_dir()),
        ]
        # quitar: el fake deja residuo en node_modules a proposito
        r = B.store_remove("alpha")
        checks += [
            ("quitar alpha no da error", r["error"] is None),
            ("el residuo en node_modules se reporta",
             r["residue"] == ["left in node_modules"]),
        ]
        # sin settings entry ni carpeta: sin residuo
        (TMP / "npm" / "node_modules" / "beta").rmdir()
        r = B.store_remove("beta")
        checks += [
            ("sin residuo no se reporta nada",
             r["error"] is None and r["residue"] == []),
        ]
    finally:
        server.shutdown()
        del B.AGENT_DIR, B.STORE_BASE, B.PKG_CMD
    return checks


async def ui():
    checks = []
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True)
    seed(str(TMP))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % port
    extra = {"PI_AGENT_DIR": str(TMP), "PI_STORE_BASE": base,
             "PI_PKG_CMD": json.dumps([sys.executable, fake_pkg_script()])}
    try:
        with Bridge(extra=extra):
            async with Page(port=9402) as p:
                js = p.js
                await p.go()
                # Chrome headless throttlea timers: el probe acorta el
                # debounce para no depender del reloj del navegador
                # (antes de setLang: si esta eval lanza, muere el script)
                await js("window.__storeDebounceMs = 50")
                await js("window.__storeCountdownMs = 100")
                await js("setLang('en')")

                # ---- la card en pi agent settings ----
                await js("paintSheet('root')")
                await asyncio.sleep(0.35)
                await js("""(()=>{[...document.querySelectorAll('#sheetBody .pick')]
                  .find(b=>/pi agent/.test(b.textContent)).click();})()""")
                await asyncio.sleep(0.4)
                cardtxt = await js("""[...document.querySelectorAll('#sheetBody .pick')]
                  .map(b=>b.querySelector('.txt span').textContent)""")
                checks.append(("la card 'Pi.dev packages' esta en pi agent",
                               "Pi.dev packages" in cardtxt))

                # ---- abrir la pagina: chips, caja, filas ----
                await js("""(()=>{[...document.querySelectorAll('#sheetBody .pick')]
                  .find(b=>/Pi.dev packages/.test(b.textContent)).click();})()""")
                await asyncio.sleep(0.4)
                lay = await js("""(()=>{
                  const b = $('#sheetBody');
                  return {q: !!b.querySelector('.storeq input'),
                          x: !!b.querySelector('.storex'),
                          chips: [...b.querySelectorAll('.chip')]
                            .map(c=>c.textContent),
                          fb: !!b.querySelector('.chipbtn'),
                          chiprow: !!b.querySelector('.chiprow'),
                          fbInChips: !!b.querySelector('.storechips .chipbtn'),
                          // primera carga (sin filas) pinta el spinner en el
                          // mismo tick; se mide ahi, que con fixture local el
                          // fetch acaba antes de que un segundo eval lo vea
                          spin: ((storeRows.length = 0), storeRefresh(),
                            !document.querySelector('.spin2').hidden),
                          nores: !!b.querySelector('#storeRes .smeta')};})()""")
                checks += [
                    ("caja de busqueda con X", lay["q"] and lay["x"]),
                    ("los cinco chips de filtro",
                     lay["chips"] == ["All types", "extension", "skill",
                                      "prompt", "Installed"]),
                    ("el boton de orden, fuera del scroller de chips",
                     lay["fb"] and lay["chiprow"]
                     and not lay["fbInChips"]),
                    ("spinner mientras carga, sin 'sin resultados'",
                     lay["spin"] and not lay["nores"]),
                ]
                # el refresh del check anterior dejo el fetch en vuelo:
                # esperar a que asiente antes de medir filas
                await asyncio.sleep(1.6)
                rows = await js("""(()=>{
                  const rs=[...document.querySelectorAll('#storeRes .pkrow')];
                  const a=rs.find(r=>r.querySelector('.snm')
                    && r.querySelector('.snm').textContent==='alpha');
                  return {n:rs.length,
                    badge: a ? !!a.querySelector('.sin') : null};})()""")
                checks += [
                    ("las 50 tarjetas de la pagina 1 salen en filas",
                     rows["n"] == 50),
                    ("alpha sale instalado con su check",
                     rows["badge"] is True),
                ]

                # ---- scroll infinito: pide la pagina 2 ----
                n2 = await js("""(()=>{const b=$('#sheetBody');
                  b.scrollTop = b.scrollHeight; return b.scrollTop > 100;})()""")
                await asyncio.sleep(1.2)
                n3 = await js("document.querySelectorAll('#storeRes .pkrow').length")
                checks += [
                    ("el scroll llego al fondo", n2 is True),
                    ("la pagina 2 se anadio (62 filas)", n3 == 62),
                ]

                # ---- chip de filtro: solo extensions ----
                await js("""(()=>{[...document.querySelectorAll('.storechips .chip')]
                  .find(c=>c.textContent==='extension').click();})()""")
                await asyncio.sleep(1.6)
                f = await js("""(()=>{
                  const on=[...document.querySelectorAll('.chip.on')]
                    .map(c=>c.textContent);
                  return {on, n:document.querySelectorAll('#storeRes .pkrow').length};})()""")
                checks += [
                    ("el chip extension queda activo", f["on"] == ["extension"]),
                    ("el filtro repinto la lista", f["n"] >= 1),
                ]

                # ---- chip con la lista bajada: fundido + loader centrado ----
                # debounce largo para ver el hueco; el scroll infinito no
                # puede colarse durante la espera (pediria la pagina 1 ya)
                await js("window.__storeDebounceMs = 1500")
                await js("$('#sheetBody').scrollTop = 600")
                await asyncio.sleep(0.4)
                await js("""(()=>{[...document.querySelectorAll('.storechips .chip')]
                  .find(c=>c.textContent==='skill').click();})()""")
                await asyncio.sleep(0.07)
                fading = await js("[+getComputedStyle($('#storeRes')).opacity,"
                                  " !!document.querySelector('#storeRes.wait')]")
                await js("$('#sheetBody').dispatchEvent(new Event('scroll'))")
                await asyncio.sleep(0.6)
                wt = await js("""(()=>{
                  const s=document.querySelector('#storeRes.wait .spin2');
                  if(!s) return null;
                  const r=s.getBoundingClientRect(),
                    b=$('#sheetBody').getBoundingClientRect(),
                    h=$('#storeHead').getBoundingClientRect(),
                    pb=parseFloat(getComputedStyle($('#sheetBody')).paddingBottom);
                  return {d: Math.abs((r.top+r.height/2) - (h.bottom+b.bottom-pb)/2),
                    vis: r.top > h.bottom && r.bottom < b.bottom,
                    top: $('#sheetBody').scrollTop, pend: storePending,
                    rows: document.querySelectorAll('#storeRes .pkrow').length};})()""")
                print("  chip bajado: fundiendo=%s espera=%s" % (fading, wt))
                checks += [
                    ("el chip funde los resultados viejos",
                     fading[0] < 0.9 and fading[1] is False),
                    ("y el loader entra centrado en el hueco",
                     wt is not None and wt["d"] <= 2 and wt["vis"]),
                    ("la lista vuelve arriba", wt and wt["top"] == 0),
                    ("el scroll infinito no pisa la espera",
                     wt and wt["pend"] is True and wt["rows"] == 0),
                ]
                await asyncio.sleep(1.6)
                await js("window.__storeDebounceMs = 50")

                # ---- chip installed: solo lo que hay en settings.json ----
                await js("""(()=>{[...document.querySelectorAll('.storechips .chip')]
                  .find(c=>c.textContent==='Installed').click();})()""")
                await asyncio.sleep(1.6)
                gi = await js("""(()=>{
                  const on=[...document.querySelectorAll('.chip.on')]
                    .map(c=>c.textContent);
                  const rows=[...document.querySelectorAll('#storeRes .pkrow')]
                    .map(r=>r.querySelector('.snm').textContent);
                  return {on, rows};})()""")
                checks += [
                    ("el chip Installed queda activo", gi["on"] == ["Installed"]),
                    ("solo salen los instalados (alpha)",
                     gi["rows"] == ["alpha"]),
                ]

                # ---- respuesta vieja: no pisa al filtro nuevo ----
                # el puente busca en hilos; una respuesta de un seq anterior
                # (instalados, lento) no puede reemplazar la lista actual
                stale = await js("""(()=>{
                  onRpc({type:'rpc', command:'store_search', data:{
                    seq: storeSeq - 1, page:1, total:1, hasMore:false,
                    packages:[{name:'viejo', desc:'', author:'', downloads:'',
                               date:'', types:[], installed:false}]}});
                  return [...document.querySelectorAll('#storeRes .snm')]
                    .map(e=>e.textContent);})()""")
                checks.append(("una respuesta de un seq viejo se descarta",
                               stale == ["alpha"]))

                # ---- loader: el puzzle de pi, no el aro ----
                ld = await js("""(async()=>{
                  const box = document.createElement('div');
                  box.innerHTML = '<div class="spin2"></div>';
                  document.body.appendChild(box);
                  piLoaders();
                  const sp = box.firstChild;
                  const pos = () => [...sp.children].map(t =>
                    t.style.getPropertyValue('--r') + ',' +
                    t.style.getPropertyValue('--c')).join(' ');
                  const a = pos();
                  await new Promise(r => setTimeout(r, 900));
                  const b = pos();
                  const cs = getComputedStyle(sp);
                  const res = {tiles: sp.children.length, moved: a !== b,
                    ring: cs.borderTopWidth, anim: cs.animationName,
                    w: sp.getBoundingClientRect().width};
                  box.remove();
                  // 2 s: el ultimo tick pudo caer en la pausa del logo (1,76 s)
                  await new Promise(r => setTimeout(r, 2000));
                  res.stopped = pilTimer === null;
                  // cierre del ciclo: el logo se queda quieto 1,5 s
                  const box2 = document.createElement('div');
                  box2.innerHTML = '<div class="spin2"></div>';
                  document.body.appendChild(box2);
                  // a un paso del logo: se deshace el ultimo movimiento
                  pilStep = PIL_SEQ.length - 1;
                  PIL_START.forEach((v, k) => pilPos[k] = v);
                  const [s0, d0] = PIL_SEQ[pilStep];  // ultimo: 13 -> 12
                  pilPos[pilPos.indexOf(d0)] = s0;
                  piLoaders();
                  await new Promise(r => setTimeout(r, 600));
                  const logo = pilPos.join() === PIL_START.join();
                  const at = pilStep;
                  await new Promise(r => setTimeout(r, 900));   // aun en pausa
                  res.hold = logo && pilStep === at;
                  await new Promise(r => setTimeout(r, 1100));  // 2,6 s: sigue
                  res.resume = pilStep > at;
                  box2.remove();
                  return res;})()""")
                print("  loader: %s" % ld)
                checks += [
                    ("el loader son las 10 fichas del logo",
                     ld["tiles"] == 10),
                    ("las fichas se desplazan", ld["moved"] is True),
                    ("sin aro ni rotacion",
                     ld["ring"] == "0px" and ld["anim"] == "none"),
                    ("tamano de icono (24 px, sin juntas)", round(ld["w"]) == 24),
                    ("sin loaders en pantalla, el reloj se para",
                     ld["stopped"] is True),
                    ("en el logo se para 1,5 s", ld["hold"] is True),
                    ("y luego sigue el ciclo", ld["resume"] is True),
                ]

                # ---- el chip activo lleva el tinte de los presets ----
                tint = await js("""getComputedStyle([...document
                  .querySelectorAll('.chip')].find(c=>c.classList
                  .contains('on'))).backgroundColor""")
                checks.append(("el chip seleccionado se tinta de ambar",
                               tint not in ("", "rgba(0, 0, 0, 0)")))

                # ---- el skeleton del detalle es fiel al layout ----
                sk = await js("""(()=>{openModal('t',
                  storeDetailSkeleton('alpha', false), null);
                  const b=$('#modalBody');
                  const s=b.querySelector('.skel');
                  const r={n:b.querySelectorAll('.skel').length,
                    name:b.querySelector('.pdname')?.textContent,
                    anim:s?getComputedStyle(s,'::after').animationName:null};
                  closeModal(); return r;})()""")
                checks += [
                    ("skeleton fiel al layout: solo el nombre real",
                     sk["name"] == "alpha" and sk["n"] >= 15),
                    ("skeleton con barras animadas (tshine)",
                     sk["anim"] == "tshine"),
                ]

                # ---- debounce: teclear no dispara al instante ----
                await js("""(()=>{[...document.querySelectorAll('.storechips .chip')]
                  .find(c=>c.textContent==='All types').click();})()""")
                await asyncio.sleep(1.6)
                h0 = HITS["list"]
                # este paso mide el debounce real de 1 s: se quita el hook
                await js("window.__storeDebounceMs = null")
                await js("""(()=>{const i=document.querySelector('#sheetBody .storeq input');
                  i.value='zz'; i.dispatchEvent(new Event('input'));})()""")
                await asyncio.sleep(0.5)
                h1 = HITS["list"]
                await asyncio.sleep(1.0)
                h2 = HITS["list"]
                checks += [
                    ("antes del segundo no hay fetch", h1 == h0),
                    ("pasado el debounce si hay fetch", h2 == h0 + 1),
                ]

                # ---- X borra el texto ----
                xst = await js("""(()=>{
                  const x=document.querySelector('#sheetBody .storex');
                  const show=x.classList.contains('show');
                  x.click();
                  return {show, val:document.querySelector('#sheetBody .storeq input').value};})()""")
                checks.append(("la X aparece con texto y lo borra",
                               xst["show"] is True and xst["val"] == ""))

                # ---- menu de orden ----
                await js("document.querySelector('.chipbtn').click()")
                await asyncio.sleep(0.25)
                pop = await js("""(()=>{const p=document.querySelector('.ctxpop');
                  return p?[...p.querySelectorAll('.ctxrow')].map(b=>b.textContent):[];})()""")
                checks.append(("el menu de orden trae las tres opciones",
                               pop == ["Most downloads", "Recently published",
                                       "A-Z"]))
                await js("document.body.click()")

                # ---- detalle: modal con todos los campos ----
                # el fixture local puede agotar sockets y una busqueda
                # puede fallar: si la fila no esta, se relanza la busqueda;
                # se mide hasta el contenido real (el modal abre antes,
                # con skeleton)
                for _ in range(4):
                    await js("""(()=>{const r=[...document
                      .querySelectorAll('#storeRes .pkrow')]
                      .find(x=>x.querySelector('.snm')
                        && x.querySelector('.snm').textContent==='alpha');
                      if(!r){ storeRefresh(); return; }
                      r.click();})()""")
                    for _ in range(25):
                        if await js("!!document.querySelector('#modalBody .pdrow')"):
                            break
                        await asyncio.sleep(0.2)
                    if await js("!!document.querySelector('#modalBody .pdrow')"):
                        break
                    await asyncio.sleep(1.0)   # deja asentarse el repaint

                det = await js("""(()=>{
                  const b=$('#modalBody');
                  return {open:$('#modal').classList.contains('open'),
                    t:$('#modalTitle').textContent,
                    name:b.querySelector('.pdname')?.textContent,
                    sec:!!b.querySelector('.pdsec'),
                    cmd:b.querySelector('.pdcode')?.textContent,
                    rows:[...b.querySelectorAll('.pdrow .k')]
                      .map(k=>k.textContent),
                    man:!![...b.querySelectorAll('.pdlbl')]
                      .some(l=>/manifest/i.test(l.textContent)),
                    links:[...b.querySelectorAll('.pdlinks a')]
                      .map(a=>a.textContent),
                    readme:!!b.querySelector('.pdreadme'),
                    ok:$('#modalOk').textContent};})()""")
                checks += [
                    ("el modal abre con 'Package details'",
                     det["open"] and det["t"] == "Package details"),
                    ("nombre, nota de seguridad y comando",
                     det["name"] == "alpha" and det["sec"]
                     and det["cmd"] == "pi install npm:alpha"),
                    ("los campos del dl salen en filas",
                     det["rows"] == ["Version", "Published", "Downloads",
                                     "Author", "License", "Types", "Size",
                                     "Dependencies"]),
                    ("el manifest JSON va en su caja", det["man"]),
                    ("los enlaces npm/repo abren fuera",
                     det["links"] == ["npm", "repo"]),
                    ("la fila Readme esta", det["readme"]),
                    ("alpha instalado: el boton dice Uninstall",
                     det["ok"].startswith("Uninstall")),
                ]

                # ---- readme: pagina completa del sheet ----
                await js("document.querySelector('.pdreadme').click()")
                await asyncio.sleep(0.5)
                rm = await js("""({page:sheetPage,
                  t:$('#sheetTitle').textContent,
                  h1:document.querySelector('#sheetBody .storemd h1')
                     ?.textContent})""")
                # la reescritura, sobre un div de prueba: las del fixture
                # fallan (loopback) y se quitan antes de poder medirlas
                rw = await js("""(()=>{const d=document.createElement('div');
                  d.innerHTML='<img src="https://x.test/a.png">'
                    + '<img src="rel.png">'
                    + '<picture><source srcset="https://x.test/b.png">'
                    + '<img src="https://x.test/c.png" srcset="https://x.test/c2.png 2x">'
                    + '</picture>';
                  readmeImgs(d);
                  const im=[...d.querySelectorAll('img')];
                  return {src: im.map(i=>i.getAttribute('src')),
                    srcset: im.some(i=>i.hasAttribute('srcset')),
                    source: d.querySelectorAll('source').length};})()""")
                print("  reescritas: %s" % rw)
                checks += [
                    ("el readme abre su pagina", rm["page"] == "pkgreadme"),
                    ("el contenido se renderiza", rm["h1"] == "Alpha"),
                    ("las imagenes van por el puente, nunca a terceros",
                     len(rw["src"]) == 2 and all(
                         i.startswith("/api/img?token=") for i in rw["src"])
                     and "u=https%3A%2F%2Fx.test%2Fa.png" in rw["src"][0]),
                    ("la relativa se quita (pediria rutas del puente)",
                     not any("rel.png" in i for i in rw["src"])),
                    ("srcset y <source> fuera (tambien apuntan fuera)",
                     not rw["srcset"] and rw["source"] == 0),
                ]
                # la del fixture vive en 127.0.0.1: el puente la rechaza y
                # la imagen rota se quita, sin icono roto
                await asyncio.sleep(1.5)
                left = await js("document.querySelectorAll("
                                "'#sheetBody .storemd img').length")
                checks.append(("una imagen que no llega se quita", left == 0))
                await js("""window.__sent = [];
                  const _ws = ws.send.bind(ws);
                  ws.send = x => { __sent.push(JSON.parse(x).type); _ws(x); };""")
                await js("goBack()")
                await asyncio.sleep(0.4)
                sent = await js("__sent")
                checks += [
                    ("atras vuelve al store", (await js("sheetPage")) == "store"),
                    ("salir del readme borra las imagenes del puente",
                     "store_img_clear" in sent),
                ]
                # cerrar la hoja entera desde el readme tambien limpia
                await js("$('#sheet').classList.add('open'); goPage('pkgreadme')")
                await asyncio.sleep(0.5)
                await js("__sent.length = 0; $('#sheet').classList.remove('open')")
                await asyncio.sleep(0.2)
                sent = await js("__sent")
                checks.append(("cerrar la hoja en el readme tambien limpia",
                               "store_img_clear" in sent))
                await js("menuSheet(); goPage('store')")
                await asyncio.sleep(0.8)

                # ---- instalar beta: countdown + flujo ----
                # la fila abre el detalle; su OK lanza la confirmacion
                await js("""(()=>{[...document.querySelectorAll('#storeRes .pkrow')]
                  .find(r=>r.querySelector('.snm')
                    && r.querySelector('.snm').textContent==='beta')
                  .click();})()""")
                for _ in range(25):
                    if await js("!!document.querySelector('#modalBody .pdrow')"):
                        break
                    await asyncio.sleep(0.2)
                await js("$('#modalOk').click()")
                # medir ya: con el hook de 100 ms el countdown acaba en 300
                c0 = await js("""({dis:$('#modalOk').disabled,
                  t:$('#modalOk').textContent,
                  title:$('#modalTitle').textContent})""")
                checks += [
                    ("el dialogo de instalacion abre",
                     c0["title"] == "Install package"),
                    ("el boton va deshabilitado 3 s",
                     c0["dis"] is True and c0["t"].endswith("(3)")),
                ]
                await asyncio.sleep(0.6)
                c1 = await js("""({dis:$('#modalOk').disabled,
                  t:$('#modalOk').textContent})""")
                checks.append(("pasados 3 s el boton se habilita",
                               c1["dis"] is False and c1["t"] == "Install"))
                await js("$('#modalOk').click()")
                await asyncio.sleep(0.3)
                busy = await js("""({spin:!!$('#modalBody .spin2'),
                  ok:$('#modalOk').disabled,
                  no:$('#modalNo').hidden})""")
                checks += [
                    ("el estado instalando muestra spinner",
                     busy["spin"] and busy["ok"] is True),
                    ("cancelar sigue visible", busy["no"] is False),
                ]
                await asyncio.sleep(1.5)   # el fake duerme 0,5 s
                done = await js("""({t:$('#modalTitle').textContent,
                  p:$('#modalBody p')?.textContent,
                  ok:$('#modalOk').disabled, no:$('#modalNo').hidden})""")
                checks += [
                    ("el mensaje de exito avisa del reinicio",
                     "beta installed" in done["p"]
                     and "Restart pi-remote" in done["p"]),
                    ("un solo boton OK al final",
                     done["ok"] is False and done["no"] is True),
                ]
                await js("$('#modalOk').click()")
                await asyncio.sleep(0.3)

                # ---- quitar alpha: residuo reportado ----
                await js("""(()=>{[...document.querySelectorAll('#storeRes .pkrow')]
                  .find(r=>r.querySelector('.snm')
                    && r.querySelector('.snm').textContent==='alpha')
                  .click();})()""")
                for _ in range(25):
                    if await js("!!document.querySelector('#modalBody .pdrow')"):
                        break
                    await asyncio.sleep(0.2)
                # el detalle abre; su OK (Uninstall) lanza la confirmacion
                await js("$('#modalOk').click()")
                for _ in range(15):
                    if await js('$("#modalTitle").textContent'
                               ' === "Remove package"'):
                        break
                    await asyncio.sleep(0.2)
                for _ in range(15):
                    r0 = await js("$('#modalOk').textContent")
                    if str(r0).startswith("Uninstall"):
                        break
                    await asyncio.sleep(0.2)
                checks.append(("el dialogo de quitar abre",
                               str(r0).startswith("Uninstall")))
                # el countdown puede tardar (throttle de timers en headless):
                # clic hasta que salga el spinner; pulsar deshabilitado no hace nada
                # el countdown puede tardar (throttle de timers en headless):
                # clic hasta que salga el spinner; pulsar deshabilitado no hace nada.
                # 30 iter: bajo carga, el throttle estira los ticks mas alla
                # de 4,5 s y el probe daba por perdida la carrera
                for _ in range(30):
                    await js("$('#modalOk').click()")
                    if await js("!!document.querySelector('#modalBody .spin2')"):
                        break
                    await asyncio.sleep(0.3)
                await asyncio.sleep(1.2)
                rd = await js("""[...$('#modalBody').querySelectorAll('p')]
                  .map(x=>x.textContent)""")
                checks += [
                    ("el quitar avisa del reinicio",
                     any("alpha removed" in x for x in rd)),
                    ("el residuo se reporta",
                     any("Residue found" in x and "node_modules" in x
                         for x in rd)),
                ]
    finally:
        # close() sin shutdown(): un cliente que no lee no puede secuestrar el fin
        server.socket.close()
        server.server_close()
    return checks


async def main():
    return backend() + await ui()


raise SystemExit(report(asyncio.run(main())))
