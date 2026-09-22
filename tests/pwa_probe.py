"""La PWA: manifest, service worker e iconos servidos, el SW se registra,
y el token se recuerda para la app instalada (que arranca sin ?token=).

En localhost el navegador da contexto seguro, asi que el service worker
se registra sin HTTPS. Contra fake_pi, sin agente real.
"""
import asyncio
import json
import urllib.request

from harness import Bridge, Page, PORT, URL, report

BASE = "http://127.0.0.1:%d" % PORT


def get(path):
    r = urllib.request.urlopen(BASE + path, timeout=4)
    return r.status, r.headers.get("content-type", ""), r.read()


async def main():
    checks = []
    with Bridge():
        # --- lo que sirve el puente
        st, ct, body = get("/manifest.webmanifest")
        man = json.loads(body.decode())
        print("  manifest: %s %s icons=%d start=%s"
              % (st, ct, len(man.get("icons", [])), man.get("start_url")))
        checks += [
            ("el manifest se sirve como manifest",
             st == 200 and "manifest" in ct),
            ("con start_url y scope en la raiz",
             man.get("start_url") == "/" and man.get("scope") == "/"),
            ("a pantalla completa, con caida a standalone",
             man.get("display") == "fullscreen"
             and man.get("display_override") == ["fullscreen", "standalone"]),
            ("con icono normal y maskable",
             any(i["sizes"] == "512x512" for i in man["icons"])
             and any(i.get("purpose") == "maskable" for i in man["icons"])),
        ]

        st, ct, body = get("/sw.js")
        sw = body.decode()
        print("  sw.js: %s %s  cache=%s"
              % (st, ct, [l for l in sw.splitlines()
                          if "CACHE" in l][0].strip()))
        checks += [
            ("el service worker se sirve como javascript",
             st == 200 and "javascript" in ct),
            ("con la version inyectada, no el marcador",
             "__VERSION__" not in sw and "piremote-" in sw),
        ]

        st, ct, body = get("/icons/icon-192.png")
        print("  icono: %s %s %d bytes" % (st, ct, len(body)))
        checks += [
            ("los iconos se sirven como png",
             st == 200 and ct == "image/png" and len(body) > 500),
        ]
        # un icono fuera de sitio se rechaza
        try:
            bad = urllib.request.urlopen(BASE + "/icons/..%2fsw.js",
                                         timeout=4).status
        except Exception as e:
            bad = getattr(e, "code", "err")
        print("  icono travieso: %s" % bad)
        checks.append(("no se puede pedir cualquier fichero por /icons",
                       bad != 200))

        # --- en el navegador: registro del SW y token recordado
        async with Page(port=9318) as p:
            js = p.js
            await p.go()                       # entra con ?token=...
            await asyncio.sleep(0.6)
            reg = await js("(async () => {"
                           " try { const r = await navigator.serviceWorker"
                           ".ready; return !!r; } catch(e){ return false; }"
                           "})()")
            saved = await js("localStorage.getItem('pi.token')")
            print("  SW registrado=%s  token guardado=%r" % (reg, saved))
            checks += [
                ("el service worker se registra en contexto seguro",
                 reg is True),
                ("la primera visita guarda el token", saved == "probe-token"),
            ]

            # la PWA instalada arranca sin ?token=: debe salir del guardado
            await p.cmd("Page.navigate", url=BASE + "/")
            await asyncio.sleep(0.8)
            tok = await js("TOKEN")
            hasQuery = await js("location.search")
            print("  sin query: search=%r  TOKEN=%r" % (hasQuery, tok))
            checks += [
                ("la app instalada recupera el token del guardado",
                 tok == "probe-token" and hasQuery == ""),
            ]

            # el color queda puesto ANTES del primer paint: Android lo lee al
            # pasar de su splash a la pagina, y si cambia despues la barra se
            # queda negra. El script #bootbar va tras el <style>, cuando las
            # variables del tema ya resuelven y no se ha pintado nada
            early = await p.js("""(()=>{
              const m=document.querySelector('meta[name="theme-color"]');
              const plate=getComputedStyle(document.documentElement)
                .getPropertyValue('--plate-a').trim();
              const bb=document.getElementById('bootbar');
              const st=document.querySelector('style');
              return {yaPuesto: m.content.toLowerCase()===plate.toLowerCase(),
                trasElStyle: !!(bb && st &&
                  (st.compareDocumentPosition(bb) & Node.DOCUMENT_POSITION_FOLLOWING)),
                anteDelCuerpo: !!(bb && document.body &&
                  (bb.compareDocumentPosition(document.body)
                    & Node.DOCUMENT_POSITION_FOLLOWING))};})()""")
            checks += [
                ("la barra ya trae su color de salida, sin esperar al JS",
                 early["yaPuesto"] is True),
                ("el script va tras el estilo y antes del cuerpo",
                 early["trasElStyle"] and early["anteDelCuerpo"]),
            ]

            # ---- la barra del sistema sigue al tema ----
            # Chrome Android no repinta la barra solo con cambiar el content
            # del meta: hay que reinsertar el nodo para que lo relea. El
            # repintado en si es del sistema y no se puede medir desde aqui;
            # lo que se mide es el color puesto y que el nodo se reinserta
            bar = await p.js("""(()=>{
              const m = () => document.querySelector('meta[name="theme-color"]');
              setTheme('pi', 'dark');
              const dark = m().content;
              const last = document.head.lastElementChild === m();
              setTheme('pi', 'light');
              const light = m().content;
              const plate = getComputedStyle(document.documentElement)
                .getPropertyValue('--plate-a').trim();
              return {dark, light, plate, last,
                      sigue: light.toLowerCase() === plate.toLowerCase()};})()""")
            await p.js("setTheme('pi','dark')")
            vis = await p.js("""(()=>{
              const m = document.querySelector('meta[name="theme-color"]');
              m.content = '#000000';                 // como si no se aplicara
              document.dispatchEvent(new Event('visibilitychange'));
              return document.querySelector('meta[name="theme-color"]').content;
              })()""")
            checks += [
                ("la barra toma el color de la toolbar del tema",
                 bar["sigue"] is True and bar["dark"] != bar["light"]),
                ("el meta se reinserta para que el sistema lo relea",
                 bar["last"] is True),
                ("y al volver a la app se reaplica solo",
                 vis.lower() != "#000000"),
            ]
    return checks


raise SystemExit(report(asyncio.run(main())))
