"""Los comandos que actuan de verdad ahora preguntan antes.

El websocket del cliente se intercepta, asi que nada de esto llega al puente."""
import asyncio
import json

from harness import Bridge, FakeProject, Page, ROOT, URL, report

# nada sale de la pagina: se apunta y se descarta
SPY = """
window.__sent = [];
ws.send = s => window.__sent.push(JSON.parse(s).type);
"""

STATE = """
window.__sent = [];
document.querySelector('#modal').classList.remove('open');
"""

async def main():
    with Bridge():
        async with Page(port=9305) as p:
            js, cmd = p.js, p.cmd
            await p.go()
            await js("setLang('es')")
            await js(SPY)

            checks = []
            for name, expect in (("compact", "compact"),
                                 ("clearq", "clear_queue"),
                                 ("new", "new_session")):
                await js(STATE)
                await js("CMDS.find(c=>c.n==='%s').run()" % name)
                await asyncio.sleep(0.35)
                st = await js("[$('#modal').classList.contains('open'),"
                              " $('#modalNo').hidden,"
                              " $('#modalOk').classList.contains('danger'),"
                              " window.__sent.length,"
                              " $('#modalTitle').textContent]")
                print("  /%-8s pregunta %-5s dos botones %-5s  aviso %-5s"
                      "  enviado %s" % (name, st[0], not st[1], st[2], st[3]))
                print("           %r" % st[4])
                checks.append(("/" + name + " pregunta antes",
                               st[0] and not st[1] and st[2] and st[3] == 0))

                # cancelar no debe hacer nada
                await js("$('#modalNo').click()")
                await asyncio.sleep(0.3)
                after = await js("[$('#modal').classList.contains('open'),"
                                 " window.__sent.length]")
                checks.append(("/" + name + " cancelar no envia",
                               after[0] is False and after[1] == 0))

                # confirmar si
                await js("CMDS.find(c=>c.n==='%s').run()" % name)
                await asyncio.sleep(0.3)
                await js("$('#modalOk').click()")
                await asyncio.sleep(0.3)
                sent = await js("window.__sent")
                checks.append(("/" + name + " confirmar envia " + expect,
                               sent == [expect]))

            # un dialogo informativo sigue con un solo boton
            await js("$('#modal').classList.remove('open'); aboutModal()")
            await asyncio.sleep(0.3)
            info = await js("[$('#modalNo').hidden,"
                            " $('#modalOk').classList.contains('danger')]")
            checks.append(("informativo: un boton, sin aviso",
                           info[0] is True and info[1] is False))

            return report(checks)

raise SystemExit(asyncio.run(main()))
