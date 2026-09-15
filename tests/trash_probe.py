"""Papelera: listar las conversaciones borradas y restaurarlas.

Backend: trash_session mueve a _trash, list_trashed las ve, restore_session las
devuelve a su carpeta. UI: boton en el rail, vista tipo busqueda con cards
(titulo + ruta), y al pulsar una card un dialogo Cancelar/Restaurar; al
restaurar la card se va y el arbol se refresca.
"""
import asyncio
from pathlib import Path

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

        # purga: borra de verdad, y solo desde _trash
        B.trash_session(str(f0), None)
        tp2 = B.list_trashed([proj.path])[0]["path"]
        pwhy = B.purge_session(tp2)
        print("  purge: why=%r  existe=%s" % (pwhy, Path(tp2).exists()))
        checks += [
            ("purge_session borra el fichero de verdad",
             pwhy == "" and not Path(tp2).exists()),
            ("no purga algo que no esta en _trash",
             B.purge_session(str(f0)) == "not_trashed"),
        ]
    return checks


CARDS = ("$('#trashView').classList.add('on'); $('#trashList').innerHTML='';"
         "[{path:'/s/_trash/a.jsonl',cwd:'C:/Users/me/proj',label:'chat viejo',"
         "mtime:2},{path:'/s/_trash/b.jsonl',cwd:'C:/Users/me/proj',"
         "label:'otro chat',mtime:1}].forEach(function(x){"
         "$('#trashList').appendChild(trashRow(x));})")


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

            btn = await p.js("[!!$('#trashBtn'), !!$('#trashBtn').querySelector('svg')]")
            checks.append(("el rail tiene el boton de papelera con su icono",
                           btn == [True, True]))

            await p.js(CARDS)
            await asyncio.sleep(0.1)
            card = await p.js("(()=>{const c=$('#trashList .trow'); return c?"
                              "[c.querySelector('.tt').textContent,"
                              " c.querySelector('.tp').textContent,"
                              " !!c.querySelector('.tact.restore'),"
                              " !!c.querySelector('.tact.purge')]:null;})()")
            print("  card: %r" % card)
            checks.append(("la card muestra titulo, ruta y los dos botones",
                           card == ["chat viejo", "C:/Users/me/proj", True, True]))

            # restaurar por su boton -> dialogo (por encima de la vista) -> comando
            await p.js("$('#trashList .trow .tact.restore').click()")
            await asyncio.sleep(0.1)
            dlg = await p.js("[$('#modal').classList.contains('open'),"
                             " $('#modalTitle').textContent, $('#modalOk').textContent,"
                             " Number(getComputedStyle($('#modal')).zIndex),"
                             " Number(getComputedStyle($('#trashView')).zIndex)]")
            print("  restaurar dialogo: %r" % dlg)
            checks += [
                ("el boton de restaurar abre su dialogo",
                 dlg[0] is True and "chat viejo" in dlg[1] and dlg[2] == "Restaurar"),
                ("y el dialogo sale por encima de la vista de papelera",
                 dlg[3] > dlg[4]),
            ]
            await p.js("window.__sent=[]; ws.send=s=>window.__sent.push("
                       "JSON.parse(s)); $('#modalOk').click()")
            await asyncio.sleep(0.1)
            rsent = await p.js("(()=>{const m=window.__sent.find(x=>x.type==="
                               "'restore_session'); return m?m.path:null;})()")
            await p.js("onRpc({command:'restore_session', data:{error:'',"
                       " path:'/s/_trash/a.jsonl'}})")
            await asyncio.sleep(0.1)
            rgone = await p.js("!$('#trashList .trow[data-path=\"/s/_trash/a.jsonl\"]')")
            checks += [
                ("restaurar manda restore_session con la ruta",
                 rsent == "/s/_trash/a.jsonl"),
                ("y su card se va", rgone is True),
            ]

            # purgar por su boton -> dialogo con aviso y boton rojo -> comando
            await p.js("$('#trashList .trow .tact.purge').click()")
            await asyncio.sleep(0.1)
            pdlg = await p.js("[$('#modal').classList.contains('open'),"
                              " $('#modalTitle').textContent,"
                              " $('#modalBody').textContent.length>0,"
                              " $('#modalOk').textContent,"
                              " $('#modalOk').classList.contains('danger')]")
            print("  purgar dialogo: %r" % pdlg)
            checks.append(("el boton de purgar abre un dialogo con aviso y en rojo",
                           pdlg[0] is True and "otro chat" in pdlg[1]
                           and pdlg[2] is True and pdlg[3] == "Eliminar"
                           and pdlg[4] is True))
            await p.js("window.__sent=[]; ws.send=s=>window.__sent.push("
                       "JSON.parse(s)); $('#modalOk').click()")
            await asyncio.sleep(0.1)
            psent = await p.js("(()=>{const m=window.__sent.find(x=>x.type==="
                               "'purge_session'); return m?m.path:null;})()")
            await p.js("onRpc({command:'purge_session', data:{error:'',"
                       " path:'/s/_trash/b.jsonl'}})")
            await asyncio.sleep(0.1)
            pgone = await p.js("[!$('#trashList .trow'), !!$('.notrash')]")
            print("  tras purgar: %r" % pgone)
            checks += [
                ("purgar manda purge_session con la ruta",
                 psent == "/s/_trash/b.jsonl"),
                ("su card se va y la vista queda vacia", pgone == [True, True]),
            ]
            checks.append(("sin errores de consola", not p.problems))
    return checks


async def main():
    return backend() + await ui()


raise SystemExit(report(asyncio.run(main())))
