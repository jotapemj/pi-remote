"""Los arreglos de seguridad siguen en pie. Nada llega al agente."""
import asyncio
import urllib.request

import websockets

from harness import Bridge, Page, PORT, URL, report

WS = "ws://127.0.0.1:%d/ws" % PORT

# una opcion de guardrails y una url, ambas con comillas dentro
XSS = r"""
window.__pwned = 0;
feed.innerHTML = ""; nodes.clear();
render({id:91, kind:"ask", method:"select",
        rid:'r" onmouseover="window.__pwned=1',
        title:'t', body:'b',
        options:['normal', '" onmouseover="window.__pwned=1']});
render({id:92, kind:"assistant", streaming:false,
        text:'[malo](https://ok.example/" onmouseover="window.__pwned=1)'});
render({id:93, kind:"user", text:'<img src=x onerror="window.__pwned=1">'});
render({id:94, kind:"assistant", streaming:false,
        text:'[bueno](https://ok.example/guia)'});
[window.__pwned,
 [...document.querySelectorAll('[onmouseover],[onerror],[onload]')].length,
 (document.querySelector('.ask') || {}).outerHTML.slice(0, 90),
 [...document.querySelectorAll('.said a')].map(a=>a.getAttribute('href'))]
"""


async def browser_side():
    async with Page(port=9309, collect_errors=True) as p:
        await p.go()
        await p.drain(1.5)

        live = await p.js("[typeof connect==='function', ws?ws.readyState:-1,"
                          " getComputedStyle(document.body).fontFamily"
                          ".includes('Jakarta'),"
                          " !!document.querySelector('#send svg')]")
        csp_err = [t for t in p.problems
                   if "Content Security Policy" in t[1] or "CSP" in t[1]]
        print("  con CSP: script=%s socket=%s fuente=%s iconos=%s"
              % tuple(live))
        print("  violaciones de CSP:", csp_err or "ninguna")

        r = await p.js(XSS)
        print("  tras inyectar: pwned=%s manejadores=%s" % (r[0], r[1]))
        print("  atributo   :", r[2][:74])
        print("  enlaces    :", r[3])

        return [
            ("la CSP no rompe la pagina",
             live[0] and live[1] == 1 and live[2] and live[3]),
            ("no hay violaciones de CSP", not csp_err),
            ("no se ejecuta nada inyectado", r[0] == 0),
            ("no aparecen manejadores en el dom", r[1] == 0),
            ("las comillas quedan escapadas", "&quot;" in r[2]),
            ("el enlace legitimo sigue funcionando",
             "https://ok.example/guia" in r[3]),
            ("una url con comillas ya no es enlace", len(r[3]) == 1),
        ]


async def origin_side():
    async def opens(headers=None):
        try:
            async with websockets.connect(
                    WS, additional_headers=headers) as w:
                await asyncio.wait_for(w.recv(), 5)
            return True
        except Exception:
            return False

    none = await opens()
    same = await opens({"Origin": "http://127.0.0.1:%d" % PORT})
    evil = await opens({"Origin": "https://evil.example"})
    print("  Origin: sin=%s propio=%s ajeno=%s" % (none, same, evil))
    return [
        ("un cliente sin Origin entra (curl, harness)", none),
        ("el propio navegador entra", same),
        ("una web ajena queda fuera", not evil),
    ]


async def main():
    with Bridge():
        checks = await browser_side()
        checks += await origin_side()

        with urllib.request.urlopen(URL, timeout=5) as r:
            h = {k.lower(): v for k, v in r.headers.items()}
        print("  cabeceras:", ", ".join(sorted(
            k for k in h if k.startswith(("content-security", "x-content",
                                          "referrer")))))
        checks.append(("cabeceras de seguridad presentes",
                       "content-security-policy" in h
                       and h.get("x-content-type-options") == "nosniff"))
        return report(checks)


raise SystemExit(asyncio.run(main()))
