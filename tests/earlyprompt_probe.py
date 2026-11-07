"""Prompt temprano: el usuario abre una sesion nueva y escribe antes de que
termine de cargar. Antes el puente mandaba el prompt a pi, pintaba la burbuja
y al llegar el historial borraba el log: la burbuja se perdia y solo quedaba
la respuesta. Ahora el prompt espera a la carga y sale despues.
FAKE_NEW_SESSION_DELAY hace que pi tarde en crear la sesion."""
import asyncio
import json

from harness import Bridge, FakeProject, Page, report


async def until(p, expr, timeout=10.0, step=0.1):
    for _ in range(int(timeout / step)):
        if await p.js(expr):
            return True
        await asyncio.sleep(step)
    return False


USER = ("[...document.querySelectorAll('.turn')].filter(e => e.__item"
        " && e.__item.kind === 'user' && e.__item.text === 'early bird')"
        ".length")
ANSWER = ("[...document.querySelectorAll('.turn')].some(e => e.__item"
          " && e.__item.kind === 'assistant')")


async def main():
    checks = []
    with Bridge(extra={"FAKE_NEW_SESSION_DELAY": "1.5"}), \
            FakeProject() as proj:
        async with Page(port=9343) as p:
            js = p.js
            await p.go()
            await js("send({type:'open_project', path:%s})"
                     % json.dumps(proj.path))
            await until(p, "state.running === false && !state.loading")
            await asyncio.sleep(1.0)

            # sesion nueva y, sin esperar, el prompt
            await js("send({type:'new_session'})")
            await asyncio.sleep(0.2)
            await js("send({type:'prompt', message:'early bird'})")

            await asyncio.sleep(0.6)
            checks.append(("no se pinta antes de cargar la sesion",
                           await js(USER) == 0))
            shown = await until(p, USER + " === 1")
            checks.append(("la burbuja aparece tras la carga", shown))
            # el fallo: la carga llegaba despues y borraba la burbuja
            await asyncio.sleep(5)
            checks.append(("sigue ahi al acabar el turno",
                           await js(USER) == 1))
            checks.append(("pi contesto", await js(ANSWER)))
    return checks


if __name__ == "__main__":
    raise SystemExit(report(asyncio.run(main())))
