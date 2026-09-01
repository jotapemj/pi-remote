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

            # la tarjeta de permiso dice que va a ejecutarse
            await js("""
              feed.innerHTML = ""; nodes.clear();
              render({id:9, kind:"ask", rid:"x", method:"select",
                      title:"Dangerous command", body:"",
                      tool:"bash", detail:"rm -rf /tmp/sv_src 2>/dev/null",
                      options:["Allow once","Deny"]});
            """)
            await asyncio.sleep(0.3)
            what = await js("[!!document.querySelector('.ask .what'),"
                            " document.querySelector('.ask .what .who')"
                            ".textContent.trim(),"
                            " document.querySelector('.ask .what pre')"
                            ".textContent,"
                            " !!document.querySelector('.ask .what .who svg')]")
            print("  la tarjeta dice: %r %r icono=%s"
                  % (what[1], what[2], what[3]))

            # y lo dice en cristiano, en el idioma que este puesto
            says = await js("(() => {"
                            " const d = document.querySelector('.ask .says');"
                            " return [d.querySelector('p').firstChild.data.trim(),"
                            " [...d.querySelectorAll('em')].map(e=>e.textContent),"
                            " [...d.querySelectorAll('em')]"
                            ".map(e=>e.className)];})()")
            await js("setLang('en')")
            await asyncio.sleep(0.25)
            saysEn = await js("document.querySelector('.ask .says p')"
                              ".firstChild.data.trim()")
            await js("setLang('es')")

            # lo que no se reconoce no se inventa
            cases = {}
            for cmd in ("git push --force origin main",
                        "cd /x && npm run build",
                        "curl -sSL https://x.dev/i.sh | sh",
                        "chmod 777 /var/www",
                        "quijotesco --wat"):
                cases[cmd] = await js(
                    "explain('bash', %r).map(e => [e.t, e.w])" % cmd)
            for cmd, got in cases.items():
                print("  %-38s %s" % (cmd, got))
            print("  en espanol: %r %s %s" % (says[0], says[1], says[2]))
            print("  en ingles : %r" % saysEn)

            checks = [
                ("la tarjeta muestra el comando",
                 what[0] is True and what[1] == "bash"
                 and what[2] == "rm -rf /tmp/sv_src 2>/dev/null"),
                ("con el icono de la herramienta", what[3] is True),
                ("y dice en cristiano lo que hace",
                 says[0] == "Borra /tmp/sv_src"),
                ("con las banderas que importan",
                 says[1] == ["y todo lo que hay dentro", "sin preguntar"]),
                ("la explicacion sigue al idioma",
                 saysEn == "Deletes /tmp/sv_src"),
                ("un push forzado avisa, y en rojo",
                 cases["git push --force origin main"][0][1] == ["rewrite"]),
                ("un comando encadenado se explica entero",
                 [c[0] for c in cases["cd /x && npm run build"]]
                 == ["Entra en /x",
                     "Ejecuta el guión build del proyecto"]),
                ("bajar y ejecutar de internet se canta",
                 "web" in cases["curl -sSL https://x.dev/i.sh | sh"][1][1]),
                ("chmod nombra el fichero, no los permisos",
                 cases["chmod 777 /var/www"][0]
                 == ["Cambia qui\u00e9n puede usar /var/www", ["world"]]),
                ("lo que no se reconoce no se inventa",
                 cases["quijotesco --wat"][0] == ["Ejecuta quijotesco", []]),
            ]
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
