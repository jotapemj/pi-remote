"""/restart: el puente dispara un comando FUERA de su propio arbol de
procesos (una tarea programada, que sobrevive a su propia muerte). Si el
agente va en turno, espera a que asiente para que la ultima respuesta
llegue entera antes del kill. Aqui no se mata nada: PI_RESTART_CMD apunta
a un marcador que solo escribe en un fichero, y se mide cuando aparece.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from harness import Bridge, FakeProject, Page, report


async def until(p, expr, timeout=8.0, step=0.1):
    for _ in range(int(timeout / step)):
        if await p.js(expr):
            return True
        await asyncio.sleep(step)
    return False


FAKE = '''
import os, time
with open(os.environ["RESTART_MARK"], "a", encoding="utf-8") as fh:
    fh.write(time.strftime("%H:%M:%S") + "\\n")
'''


def marks(path):
    return len(Path(path).read_text(encoding="utf-8").splitlines()) \
        if Path(path).exists() else 0


async def main():
    tmp = Path(os.environ.get("TEMP", "."))
    mark = tmp / "pi-selfrestart-mark.txt"
    fake = tmp / "pi-selfrestart-fake.py"
    if mark.exists():
        mark.unlink()
    fake.write_text(FAKE, encoding="utf-8")

    checks = []
    with Bridge(extra={"PI_RESTART_CMD":
                       json.dumps([sys.executable, str(fake)]),
                       "RESTART_MARK": str(mark)}), FakeProject() as proj:
        async with Page(port=9341) as p:
            js = p.js
            await p.go()
            await js("send({type:'open_project', path:%s})"
                     % json.dumps(proj.path))
            await until(p, "state.running === false")
            await asyncio.sleep(1.5)

            # --- en reposo: dispara en el acto ---
            await js("send({type:'restart'})")
            await asyncio.sleep(1.5)
            m1 = marks(mark)
            note1 = await js("[...document.querySelectorAll('.note')]"
                             ".some(e => /restarting|reiniciando/i.test"
                             "(e.textContent))")
            checks += [
                ("en reposo, dispara en el acto", m1 == 1),
                ("deja su nota en el transcripto", note1 is True),
            ]

            # --- a mitad de turno: espera a que asiente ---
            await js("feed.innerHTML=''; send({type:'prompt',"
                     " message:'stopme'})")
            run = await until(p, "state.running === true")
            await js("send({type:'restart'})")
            await asyncio.sleep(0.6)
            early = marks(mark)      # todavia no: el turno va en curso
            await until(p, "state.running === false")
            await asyncio.sleep(1.5)
            late = marks(mark)
            checks += [
                ("el turno en curso arranca", run is True),
                ("no dispara mientras el agente trabaja", early == 1),
                ("dispara al asentarse el turno", late == 2),
            ]

    fake.unlink(missing_ok=True)
    if mark.exists():
        mark.unlink()
    return report(checks)


raise SystemExit(asyncio.run(main()))
