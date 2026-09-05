"""Cada comando de la paleta da feedback observable: nota en el chat, dialogo,
o picker. Cubre los tres que estaban mudos (stats, state, last) y un barrido de
los demas, para que no se cuele otro sin respuesta al pulsarlo.
"""
import asyncio
import json

from harness import Bridge, Page, report


async def main():
    checks = []
    with Bridge():
        async with Page(port=9382) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")
            await js("state={running:false,waiting:false,alive:true,cwd:'C:/proj',"
                     "sessionName:'mi sesion',model:'Qwen3.8-27B',thinking:'off',"
                     "context:{percent:56.79,tokens:60000,window:131000,"
                     "cost:0.0123}, queue:{steering:[],followUp:[]},recent:[]};"
                     " paint()")

            async def run(name, arg="null"):
                await js("feed.innerHTML=''; nodes.clear();"
                         " $('#modal').classList.remove('open');"
                         " $('#sheet').classList.remove('open');"
                         " CMDS.find(c=>c.n===%s).run(%s)"
                         % (json.dumps(name), arg))
                await asyncio.sleep(0.05)

            async def note_text():
                # todas las notas juntas: /stats y /state tambien hacen send()
                # y, sin proyecto abierto, el puente suma una nota "sin proyecto"
                return await js("[...document.querySelectorAll('#feed .note')]"
                                ".map(n=>n.textContent).join(' | ')")

            async def dialog():
                return await js("!!document.querySelector('#modal.open, "
                                "#sheet.open')")

            # --- los tres que estaban mudos ---
            await run("stats")
            st = await note_text()
            print("  stats:", repr(st))
            checks.append(("/stats muestra una nota con contexto",
                           "%" in st and "k" in st))

            await run("state")
            st2 = await note_text()
            print("  state:", repr(st2))
            checks.append(("/state muestra sesion/modelo/razonamiento",
                           "mi sesion" in st2 and "Qwen3.8-27B" in st2))

            # last: la respuesta rpc va a una nota, NO a un alert
            await js("feed.innerHTML=''; nodes.clear(); window.__alert=false;"
                     " window.alert=()=>{window.__alert=true;};"
                     " onRpc({type:'rpc', command:'get_last_assistant_text',"
                     " data:{text:'la ultima respuesta'}})")
            await asyncio.sleep(0.05)
            last = await note_text()
            used_alert = await js("window.__alert")
            print("  last: nota=%r alert=%s" % (last, used_alert))
            checks += [
                ("/last muestra la respuesta en una nota",
                 "la ultima respuesta" in last),
                ("y no usa alert()", used_alert is False),
            ]

            # --- barrido: comandos que dan nota ---
            for name in ["cwd", "ping", "queue", "pend"]:
                await run(name)
                t = await note_text()
                print("  %-6s -> nota=%r" % (name, t[:44]))
                checks.append(("/%s da una nota" % name, bool(t)))

            # --- barrido: comandos que abren dialogo ---
            for name in ["help", "new", "compact", "clearq"]:
                await run(name)
                op = await dialog()
                print("  %-8s -> dialogo=%s" % (name, op))
                checks.append(("/%s abre un dialogo" % name, op is True))

            # --- picker via rpc: model/think/fork abren el sheet ---
            for cmd, data in [
                ("get_available_models",
                 {"models": [{"name": "m1", "provider": "p", "id": "i",
                              "contextWindow": 1000}]}),
                ("get_available_thinking_levels", {"levels": ["off", "high"]}),
                ("get_fork_messages",
                 {"messages": [{"text": "hola", "entryId": "e1"}]}),
            ]:
                await js("$('#sheet').classList.remove('open');"
                         " onRpc({type:'rpc', command:%s, data:%s})"
                         % (json.dumps(cmd), json.dumps(data)))
                await asyncio.sleep(0.05)
                op = await js("$('#sheet').classList.contains('open')")
                print("  %-32s -> picker=%s" % (cmd, op))
                checks.append(("%s abre un picker" % cmd, op is True))

            checks.append(("sin errores de consola", not p.problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
