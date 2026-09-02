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
    return checks


raise SystemExit(report(asyncio.run(main())))
