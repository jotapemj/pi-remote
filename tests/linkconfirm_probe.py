"""Enlaces del chat: tocar uno no abre a ciegas. Dialogo con el dominio, la
direccion entera (tocarla la copia) y "no volver a preguntar" por sitio,
guardado en pi.linkHosts. Abrir = window.open con noopener; aqui se
sustituye para registrar la llamada sin abrir pestanas."""
import asyncio
import json
import os

from harness import Bridge, Page, report

SHOT = os.environ.get("PI_SHOT")     # ruta opcional para ver la captura
URL = "https://example.com/docs?a=1&b=2"

SNAP = """((items) => {
  ws.onmessage({data: JSON.stringify({type: 'snapshot', items,
    state: Object.assign({}, state), cwd: CWD})});
})"""


async def main():
    checks = []
    with Bridge():
        async with Page() as p:
            js = p.js
            await p.go()
            await asyncio.sleep(0.8)
            await js("setLang('es')")
            await js("localStorage.removeItem('pi.linkHosts');"
                     " window.__opened = [];"
                     " window.open = (u, t, f) => { __opened.push([u, t, f]);"
                     " return null; }")
            await js(SNAP + "(%s)" % json.dumps([
                {"id": 1, "kind": "assistant",
                 "text": "mira [la doc](%s) y [otra](https://pi.dev/x)" % URL}]))
            await asyncio.sleep(0.3)

            await js("document.querySelector('.said a').click()")
            await asyncio.sleep(0.3)
            raw = await js("""JSON.stringify({
              open: $('#modal').classList.contains('open'),
              title: $('#modalTitle').textContent,
              host: ($('#modalBody .lkhost') || {}).textContent,
              url: ($('#modalBody .lkurl') || {}).textContent,
              ok: $('#modalOk').textContent,
              danger: $('#modalOk').classList.contains('danger'),
              opened: __opened.length})""")
            dlg = json.loads(raw)
            print("  ", dlg)
            checks += [
                ("el enlace no abre a ciegas: sale el dialogo",
                 dlg["open"] and dlg["opened"] == 0),
                ("titulo y boton en el idioma activo",
                 dlg["title"] == "¿Abrir este sitio web?"
                 and dlg["ok"] == "Abrir"),
                ("el dominio, aparte", dlg["host"] == "example.com"),
                ("la direccion entera", dlg["url"] == URL),
                ("abrir no es peligroso: boton normal", not dlg["danger"]),
            ]

            # tocar la direccion la copia: el icono pasa a check. Chrome
            # sin gesto real no deja copiar: se registra lo que llegaria
            await js("window.__clip = null; Object.defineProperty(navigator,"
                     " 'clipboard', {value: {writeText: t => {"
                     " __clip = t; return Promise.resolve(); }}})")
            await js("$('#modalBody .lkurl').click()")
            await asyncio.sleep(0.3)
            copied = await js("!!$('#modalBody .lkcp.done')"
                              " && $('#modal').classList.contains('open')"
                              " && __clip === %s" % json.dumps(URL))
            checks.append(("tocar la direccion la copia y no cierra", copied))
            if SHOT:
                await p.shot(SHOT)

            # cancelar: no abre nada
            await js("$('#modalNo').click()")
            await asyncio.sleep(0.3)
            checks.append(("cancelar no abre",
                           await js("__opened.length") == 0))

            # abrir con "no volver a preguntar"
            await js("document.querySelector('.said a').click()")
            await asyncio.sleep(0.3)
            await js("$('#linkTrustCb').checked = true; $('#modalOk').click()")
            await asyncio.sleep(0.3)
            got = json.loads(await js("JSON.stringify(__opened)"))
            checks.append(("abrir lanza la url con noopener",
                           len(got) == 1 and got[0][0] == URL
                           and "noopener" in (got[0][2] or "")))
            checks.append(("el sitio queda recordado",
                           await js("localStorage.getItem('pi.linkHosts')")
                           == '["example.com"]'))

            # mismo sitio: directo; otro sitio: vuelve a preguntar
            await js("document.querySelector('.said a').click()")
            await asyncio.sleep(0.3)
            checks.append(("sitio recordado: abre sin dialogo",
                           await js("__opened.length") == 2
                           and not await js(
                               "$('#modal').classList.contains('open')")))
            await js("document.querySelectorAll('.said a')[1].click()")
            await asyncio.sleep(0.3)
            checks.append(("otro sitio: vuelve a preguntar",
                           await js("$('#modal').classList.contains('open')")
                           and await js("$('#modalBody .lkhost').textContent")
                           == "pi.dev"))
            problems = [x for x in p.problems if "favicon" not in x[1]]
            checks.append(("sin fallos en consola", not problems))
            if problems:
                print(problems[:4])
    return checks


raise SystemExit(report(asyncio.run(main())))
