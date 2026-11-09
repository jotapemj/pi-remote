"""Arbol de la sesion (/tree): get_tree aplanado por el puente.

- Solo mensajes con texto (la llamada a herramienta y su resultado no).
- La rama abandonada sale donde nacio, un carril a la derecha, atenuada y
  rotulada; la activa sigue en su carril.
- Solo los mensajes propios de la rama activa ramifican (RPC no sabe saltar
  a una rama abandonada): esos abren la confirmacion de fork; el resto, el
  texto para leerlo.
"""
import asyncio
import json
import sys

from harness import Bridge, FakeProject, Page, report

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROWS = """[...document.querySelectorAll('#sheetBody .tnode')].map(r => ({
  t: r.querySelector('.tt').textContent,
  lane: +r.style.getPropertyValue('--lane'),
  off: r.classList.contains('off'),
  fork: !!r.querySelector('.tf svg'),
  x: Math.round(r.querySelector('.td').getBoundingClientRect().left),
  h: r.getBoundingClientRect().height}))"""


async def main():
    checks = []
    with Bridge(), FakeProject() as proj:
        async with Page() as p:
            js = p.js
            await p.go()
            await asyncio.sleep(0.8)
            await js("setLang('es'); send({type:'open_project', path:%s})"
                     % json.dumps(proj.path))
            for _ in range(40):
                if await js("state.cwd && !state.loading"):
                    break
                await asyncio.sleep(0.2)
            await asyncio.sleep(0.5)
            await js("CMDS.find(c => c.n === 'tree').run()")
            rows = []
            for _ in range(40):
                rows = await js(ROWS)
                if rows:
                    break
                await asyncio.sleep(0.2)
            title = await js("$('#sheetTitle').textContent")
            for r in rows:
                print("   ", r)
            texts = [r["t"] for r in rows]
            by = {r["t"].replace("Rama", ""): r for r in rows}
            checks += [
                ("la hoja se titula en el idioma activo",
                 title == "Árbol de la sesión"),
                ("solo mensajes con texto, en orden de lectura",
                 [t.replace("Rama", "") for t in texts] ==
                 ["primera pregunta", "primera respuesta",
                  "camino que se dejo", "rama vieja", "camino bueno",
                  "hecho"]),
                ("la rama abandonada, un carril a la derecha y rotulada",
                 by["camino que se dejo"]["lane"] == 1
                 and texts[2].startswith("Rama")
                 and by["camino que se dejo"]["x"]
                 > by["camino bueno"]["x"]),
                ("y atenuada; la activa no",
                 by["rama vieja"]["off"] and not by["hecho"]["off"]),
                ("solo lo propio de la rama activa ramifica",
                 [r["fork"] for r in rows]
                 == [True, False, False, False, True, False]),
                ("las filas se pintan", all(r["h"] > 0 for r in rows)),
            ]
            if __import__("os").environ.get("PI_SHOT"):
                await asyncio.sleep(1.0)       # la hoja termina de subir
                await p.shot(__import__("os").environ["PI_SHOT"])

            # una abandonada: solo leerla
            await js("[...document.querySelectorAll('#sheetBody .tnode')]"
                     ".find(r => r.textContent.includes('camino que')).click()")
            await asyncio.sleep(0.4)
            read = await js("[$('#modal').classList.contains('open'),"
                            " $('#modalTitle').textContent,"
                            " $('#modalBody').textContent]")
            checks.append(("una abandonada se abre para leerla, sin fork",
                           read == [True, "Mensaje propio",
                                    "camino que se dejo"]))
            await js("closeModal()")
            await asyncio.sleep(0.3)

            # una de la rama activa: confirmacion de fork, y fork de verdad
            await js("[...document.querySelectorAll('#sheetBody .tnode')]"
                     ".find(r => r.textContent.includes('camino bueno')).click()")
            await asyncio.sleep(0.4)
            fk = await js("[$('#modal').classList.contains('open'),"
                          " !!$('#forkTrashCb'),"
                          " $('#modalBody .forkmsg').textContent]")
            checks.append(("una propia de la rama activa pide el fork",
                           fk == [True, True, "camino bueno"]))
            await js("$('#modalOk').click()")
            forked = False
            for _ in range(30):
                forked = await js("[...nodes.values()].some(e => e.__item"
                                  " && e.__item.key === 'forked')")
                if forked:
                    break
                await asyncio.sleep(0.2)
            checks.append(("y el fork llega a pi", forked))
            problems = [x for x in p.problems if "favicon" not in x[1]]
            checks.append(("sin fallos en consola", not problems))
            if problems:
                print(problems[:4])
    return checks


raise SystemExit(report(asyncio.run(main())))
