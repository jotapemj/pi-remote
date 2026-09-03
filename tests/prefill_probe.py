"""Aviso de prefill: cuando el modelo reingiere el contexto antes del primer
token, el readout dice "prefilling…". Certero al cambiar de sesion o compactar;
por tiempo (umbral) cuando llama.cpp se reinicio. El primer token lo quita, y un
turno caliente no lo muestra nunca. pi no da senal: se infiere en el cliente.
"""
import asyncio
import json

from harness import Bridge, Page, report

WORD = "prefilling\u2026"          # T('prefilling') + '…', en ingles


def st(running, waiting=False):
    return {"running": running, "waiting": waiting, "alive": True,
            "cwd": "C:/x", "sessionName": "s", "model": "m", "thinking": "x",
            "context": {"percent": 50, "tokens": 1000, "window": 2000},
            "queue": {"steering": [], "followUp": []}, "recent": [],
            "startedAt": 1000}


async def main():
    checks = []
    with Bridge():
        async with Page(port=9372) as p:
            js = p.js
            await p.go()
            await js("setLang('en')")

            async def send(msg):
                await js("ws.onmessage({data: %s})"
                         % json.dumps(json.dumps(msg)))

            async def readout():
                return await js("[$('#rword').textContent,"
                                " $('#readout').classList.contains('prefill'),"
                                " prefilling()]")

            # --- A) sesion fria (cleared) -> prefill al arrancar el turno
            await send({"type": "state", "state": st(False)})
            await send({"type": "cleared"})
            await send({"type": "state", "state": st(True)})
            a = await readout()
            print("  A frio: rword=%r prefill=%s pred=%s" % tuple(a))
            checks += [
                ("sesion fria muestra prefill al arrancar",
                 a[0] == WORD and a[1] is True and a[2] is True),
            ]

            # --- B) el primer token lo quita
            await send({"type": "item", "item": {"id": 5, "kind": "assistant",
                        "text": "", "streaming": True}})
            await send({"type": "delta", "id": 5, "delta": "Hi"})
            await asyncio.sleep(0.3)
            b = await readout()
            print("  B primer token: rword=%r prefill=%s pred=%s" % tuple(b))
            checks += [
                ("el primer token quita el prefill",
                 b[0] != WORD and b[1] is False and b[2] is False),
            ]

            # --- C) compactacion en medio del turno -> prefill otra vez
            await send({"type": "state", "state": st(True)})   # turno caliente
            await js("produced=true")                          # ya salio algo
            mid = await js("prefilling()")
            await send({"type": "item", "item": {"id": 9, "kind": "note",
                        "level": "info", "key": "compacted",
                        "text": "context compacted: 60k to 32k"}})
            await asyncio.sleep(0.3)
            c = await readout()
            print("  C compactado: antes=%s -> rword=%r prefill=%s pred=%s"
                  % (mid, c[0], c[1], c[2]))
            checks += [
                ("antes de compactar no habia prefill", mid is False),
                ("compactar vuelve a mostrar prefill",
                 c[0] == WORD and c[1] is True and c[2] is True),
            ]

            # --- D) turno caliente y rapido: nunca prefill
            await js("produced=false; coldNext=false; turnStart=Date.now()")
            await send({"type": "state", "state": st(True)})
            d0 = await js("prefilling()")
            await send({"type": "item", "item": {"id": 7, "kind": "assistant",
                        "text": "", "streaming": True}})
            await send({"type": "delta", "id": 7, "delta": "ya"})
            await asyncio.sleep(0.3)
            d = await readout()
            print("  D caliente: arranque_pred=%s -> rword=%r prefill=%s"
                  % (d0, d[0], d[1]))
            checks += [
                ("un turno caliente no muestra prefill",
                 d0 is False and d[0] != WORD and d[1] is False),
            ]

            # --- E) heuristico: corriendo, sin token, pasado el umbral
            await js("produced=false; coldNext=false;"
                     " turnStart=Date.now()-2000")   # como si llevara 2s mudo
            await send({"type": "state", "state": st(True)})
            await asyncio.sleep(0.3)
            e = await readout()
            print("  E umbral: rword=%r prefill=%s pred=%s" % tuple(e))
            checks.append(("sin token y pasado el umbral, prefill (llama.cpp"
                           " reiniciado)", e[0] == WORD and e[2] is True))

            # --- F) etiqueta en espanol
            await js("setLang('es'); produced=false; coldNext=true;"
                     " turnStart=Date.now(); paintStatus()")
            await asyncio.sleep(0.3)
            f = await js("$('#rword').textContent")
            print("  F es: rword=%r" % f)
            checks.append(("la etiqueta va traducida",
                           f == "procesando contexto\u2026"))

            checks.append(("sin errores de consola", not p.problems))
    return checks


raise SystemExit(report(asyncio.run(main())))
