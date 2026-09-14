"""Papelera: listar las conversaciones borradas y restaurarlas.

Backend: trash_session mueve a _trash, list_trashed las ve, restore_session las
devuelve a su carpeta. UI: boton en el rail, vista tipo busqueda con cards
(titulo + ruta), y al pulsar una card un dialogo Cancelar/Restaurar; al
restaurar la card se va y el arbol se refresca.
"""
import asyncio

from harness import Bridge, FakeProject, Page, report


def backend():
    import pi_web_bridge as B
    checks = []
    with FakeProject("trash", sessions=2) as proj:
        sd = B.session_dir(proj.path)
        f0 = sorted(sd.glob("*.jsonl"))[0]
        why = B.trash_session(str(f0), None)
        listed = B.list_trashed([proj.path])
        print("  trash: why=%r  en papelera=%d" % (why, len(listed)))
        checks += [
            ("mueve a la papelera", why == "" and not f0.exists()),
            ("list_trashed la ve, con su proyecto",
             len(listed) == 1 and listed[0]["cwd"] == proj.path),
        ]

        tpath = listed[0]["path"] if listed else ""
        rwhy = B.restore_session(tpath)
        after = B.list_trashed([proj.path])
        print("  restore: why=%r  vuelve=%s  papelera_despues=%d"
              % (rwhy, f0.exists(), len(after)))
        checks += [
            ("restore_session la devuelve a su carpeta",
             rwhy == "" and f0.exists()),
            ("y ya no esta en la papelera", len(after) == 0),
        ]

        # guardas: fuera de _trash o fuera de las sesiones no se restaura
        checks += [
            ("no restaura algo que no esta en _trash",
             B.restore_session(str(f0)) == "not_trashed"),
            ("no restaura fuera de la carpeta de sesiones",
             B.restore_session("C:/x/y.jsonl") in ("outside", "bad_path")),
        ]
    return checks


CARD = ("$('#trashList').innerHTML=''; $('#trashList').appendChild(trashRow("
        "{path:'/s/_trash/a.jsonl', cwd:'C:/Users/me/proj', "
        "label:'chat viejo', mtime:1}))")


async def ui():
    checks = []
    with Bridge():
        async with Page(port=9371, collect_errors=True) as p:
            await p.go()
            await p.js("try{ if(typeof ws!=='undefined' && ws)"
                       " ws.onmessage=null; }catch(e){}")
            await p.js("setLang('es')")
            await p.js("state={running:false,waiting:false,alive:true,cwd:'C:/x',"
                       "sessionName:'s',model:'m',thinking:'x',context:null,"
                       "queue:{steering:[],followUp:[]},recent:[]}; CWD='C:/x'; paint()")

            # boton de papelera en el rail
            btn = await p.js("[!!$('#trashBtn'), !!$('#trashBtn').querySelector('svg')]")
            checks.append(("el rail tiene el boton de papelera con su icono",
                           btn == [True, True]))

            # abrir la vista y pintar una card
            await p.js("$('#trashView').classList.add('on'); " + CARD)
            await asyncio.sleep(0.1)
            card = await p.js("(()=>{const c=$('#trashList .trow'); return c?"
                              "[c.querySelector('.tt').textContent,"
                              " c.querySelector('.tp').textContent]:null;})()")
            print("  card: %r" % card)
            checks.append(("la card muestra titulo y ruta debajo",
                           card == ["chat viejo", "C:/Users/me/proj"]))

            # pulsar la card -> dialogo Cancelar/Restaurar con el nombre
            await p.js("$('#trashList .trow').click()")
            await asyncio.sleep(0.1)
            dlg = await p.js("[$('#modal').classList.contains('open'),"
                             " $('#modalTitle').textContent,"
                             " $('#modalOk').textContent]")
            print("  dialogo: abierto=%s titulo=%r ok=%r"
                  % (dlg[0], dlg[1], dlg[2]))
            checks.append(("al pulsar sale el dialogo de restaurar",
                           dlg[0] is True and "chat viejo" in dlg[1]
                           and dlg[2] == "Restaurar"))

            # restaurar: envia el comando
            await p.js("window.__sent=[]; ws.send=s=>window.__sent.push("
                       "JSON.parse(s)); $('#modalOk').click()")
            await asyncio.sleep(0.1)
            sent = await p.js("(()=>{const m=window.__sent.find(x=>x.type==="
                              "'restore_session'); return m?m.path:null;})()")
            checks.append(("restaurar envia restore_session con la ruta",
                           sent == "/s/_trash/a.jsonl"))

            # y al confirmar el puente, la card se va
            await p.js("onRpc({command:'restore_session', data:{error:'',"
                       " path:'/s/_trash/a.jsonl'}})")
            await asyncio.sleep(0.1)
            gone = await p.js("[!$('#trashList .trow'), !!$('.notrash')]")
            print("  tras restaurar: card_fuera=%s vacia=%s" % (gone[0], gone[1]))
            checks.append(("la card se va y la vista queda vacia",
                           gone == [True, True]))
            checks.append(("sin errores de consola", not p.problems))
    return checks


async def main():
    return backend() + await ui()


raise SystemExit(report(asyncio.run(main())))
