"""Fork: filtrado de inyectados, reconstruccion, papelera, y la UI.

pi trunca en el mensaje elegido y rebindea a una rama nueva. El puente:
- limpia get_fork_messages (fuera el prompt de resumen, recorta el SUGGEST_HINT),
- al forkear reconstruye el transcripto y suelta una nota "forked",
- al borrar la sesion ABIERTA sale a una nueva y papelea la vieja (no error).
La UI muestra un picker de cards altas y un dialogo de confirmacion con el
mensaje scrolleable, un checkbox de papelera, y rellena el compositor.
Sin agente real: fake_pi responde a fork/get_fork_messages.
"""
import asyncio
import json

import websockets

from harness import Bridge, FakeProject, Page, report, WS_URL


async def ws_checks():
    checks = []
    with FakeProject() as proj, Bridge():
        async with websockets.connect(WS_URL) as ws:
            await ws.recv()
            await ws.send(json.dumps({"type": "open_project", "path": proj.path}))
            await asyncio.sleep(1.5)
            try:
                while True:
                    await asyncio.wait_for(ws.recv(), 0.3)
            except asyncio.TimeoutError:
                pass

            # A) get_fork_messages: el puente limpia lo inyectado
            await ws.send(json.dumps({"type": "get_fork_messages"}))
            texts = None
            end = asyncio.get_event_loop().time() + 4
            while asyncio.get_event_loop().time() < end:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 2))
                except asyncio.TimeoutError:
                    break
                if m.get("type") == "rpc" and m.get("command") == "get_fork_messages":
                    texts = [x.get("text") for x in m["data"].get("messages", [])]
                    break
            print("  fork messages limpios: %r" % texts)
            checks += [
                ("el prompt de resumen inyectado se omite",
                 texts is not None and all("interrupted by the user" not in t
                                           for t in texts)),
                ("el SUGGEST_HINT se recorta del texto",
                 texts is not None and "do the thing" in texts
                 and not any("<hint:" in t for t in texts)),
            ]

            # B) fork: limpia el transcripto y suelta la nota forked
            await ws.send(json.dumps({"type": "fork", "entryId": "e1"}))
            cleared = forked = False
            end = asyncio.get_event_loop().time() + 4
            while asyncio.get_event_loop().time() < end:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 2))
                except asyncio.TimeoutError:
                    break
                if m.get("type") == "cleared":
                    cleared = True
                items = ([m["item"]] if m.get("type") == "item"
                         else m.get("items", []) if m.get("type") == "snapshot"
                         else [])
                if any(i.get("kind") == "note" and i.get("key") == "forked"
                       for i in items):
                    forked = True
            print("  fork: cleared=%s nota_forked=%s" % (cleared, forked))
            checks += [
                ("el fork limpia y reconstruye el transcripto", cleared),
                ("y deja una nota 'forked'", forked),
            ]

            # C) borrar la sesion ABIERTA: sale a una nueva (cleared), no error
            try:
                while True:
                    await asyncio.wait_for(ws.recv(), 0.3)
            except asyncio.TimeoutError:
                pass
            await ws.send(json.dumps({"type": "delete_session",
                                      "path": "/tmp/fake.jsonl"}))
            cleared2 = in_use = False
            end = asyncio.get_event_loop().time() + 4
            while asyncio.get_event_loop().time() < end:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 2))
                except asyncio.TimeoutError:
                    break
                if m.get("type") == "cleared":
                    cleared2 = True
                it = m.get("item") or {}
                if it.get("kind") == "note" and it.get("key") == "del_in_use":
                    in_use = True
            print("  borrar abierta: cleared=%s in_use=%s" % (cleared2, in_use))
            checks += [
                ("borrar la sesion abierta sale a una nueva",
                 cleared2 and not in_use),
            ]
    return checks


async def ui_checks():
    checks = []
    with Bridge():
        async with Page(port=9361, collect_errors=True) as p:
            await p.go()
            await p.js("try{ if(typeof ws!=='undefined' && ws)"
                       " ws.onmessage=null; }catch(e){}")   # sin pisadas del puente
            await p.js("setLang('es')")
            await p.js("state={running:false,waiting:false,alive:true,cwd:'C:/x',"
                       "sessionName:'s',model:'m',thinking:'x',context:null,"
                       "queue:{steering:[],followUp:[]},recent:[]}; CWD='C:/x'; paint()")

            await p.js("onRpc({command:'get_fork_messages', data:{messages:["
                       "{entryId:'e1',text:'hola mundo'},"
                       "{entryId:'e2',text:'segundo mensaje'}]}})")
            await asyncio.sleep(0.2)
            cards = await p.js("[...document.querySelectorAll('.fork-card')]"
                               ".map(c=>c.textContent)")
            print("  picker cards: %r" % cards)
            checks += [
                ("el picker pinta una card por mensaje",
                 cards == ["hola mundo", "segundo mensaje"]),
            ]

            await p.js("document.querySelectorAll('.fork-card')[0].click()")
            await asyncio.sleep(0.1)
            dlg = await p.js("[document.querySelector('#modal').classList"
                             ".contains('open'), !!document.getElementById("
                             "'forkTrashCb'), document.querySelector('#modalOk')"
                             ".textContent, document.querySelector('.forkmsg')"
                             "? document.querySelector('.forkmsg').textContent:'']")
            print("  dialogo: abierto=%s checkbox=%s ok=%r msg=%r"
                  % (dlg[0], dlg[1], dlg[2], dlg[3]))
            checks += [
                ("al elegir sale el dialogo con el mensaje y el checkbox",
                 dlg[0] is True and dlg[1] is True and dlg[3] == "hola mundo"),
            ]

            await p.js("window.__sent=[]; ws.send=s=>window.__sent.push("
                       "JSON.parse(s)); document.getElementById('forkTrashCb')"
                       ".checked=true; document.querySelector('#modalOk').click()")
            await asyncio.sleep(0.1)
            sent = await p.js("(()=>{const m=window.__sent.find(x=>x.type==="
                              "'fork'); return m?[m.entryId,m.trashOriginal]"
                              ":null;})()")
            boxv = await p.js("box.value")
            print("  aceptar: enviado=%s box=%r" % (sent, boxv))
            checks += [
                ("aceptar forkea el mensaje elegido con el flag de papelera",
                 sent == ["e1", True]),
                ("y rellena el compositor con ese mensaje", boxv == "hola mundo"),
            ]
            checks.append(("sin errores de consola", not p.problems))
    return checks


async def main():
    return await ws_checks() + await ui_checks()


raise SystemExit(report(asyncio.run(main())))
