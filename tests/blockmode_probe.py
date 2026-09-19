"""Animacion de generacion, modo "block": el texto no se muestra hasta que el
parrafo esta completo (hasta el ultimo doble salto de linea; al terminar el
mensaje, todo). Cada parrafo completo entra con un fade rapido (.blockin) y el
parrafo en curso queda oculto. A diferencia de "smooth", no usa
requestAnimationFrame: se pinta sincrono en el handler, asi que es medible.
"""
import asyncio
import json

from harness import Bridge, Page, report


def send(o):
    return "ws.onmessage({data: %s})" % json.dumps(json.dumps(o))


async def main():
    checks = []
    with Bridge():
        async with Page(port=9410, collect_errors=True) as p:
            js = p.js
            await p.go()
            await asyncio.sleep(0.4)          # deja asentar el snapshot inicial
            await js("setMotion('block')")
            await js("state={running:true,waiting:false,alive:true,cwd:'C:/x',"
                     "sessionName:'s',model:'m',thinking:'x',context:null,"
                     "queue:{steering:[],followUp:[]},recent:[]};"
                     "feed.innerHTML=''; nodes.clear(); paint()")

            # el primer delta llega como item (asi lo emite el puente)
            await js(send({"type": "item", "item": {"id": 5, "kind": "assistant",
                     "text": "Hello ", "streaming": True}}))
            await asyncio.sleep(0.02)
            t1 = await js("(nodes.get(5)||{}).textContent||''")

            # mas texto del parrafo en curso, aun sin cerrar: sigue oculto
            await js(send({"type": "delta", "id": 5, "delta": "world."}))
            await asyncio.sleep(0.02)
            t2 = await js("(nodes.get(5)||{}).textContent||''")

            # cierra el parrafo con doble salto: aparece el completo, con .blockin
            await js(send({"type": "delta", "id": 5, "delta": "\n\n"}))
            await asyncio.sleep(0.02)
            r3 = await js("(()=>{const b=nodes.get(5).querySelector('[data-body]');"
                          "return {tc:b.textContent, n:b.children.length,"
                          " blockin:[...b.children].map(c=>"
                          "c.classList.contains('blockin'))};})()")

            # segundo parrafo en curso: no se muestra hasta cerrarse
            await js(send({"type": "delta", "id": 5, "delta": "Second para "}))
            await js(send({"type": "delta", "id": 5, "delta": "here."}))
            await asyncio.sleep(0.02)
            t4 = await js("nodes.get(5).querySelector('[data-body]').textContent")

            # message_end: patch con el texto completo -> aparecen los dos
            full = "Hello world.\n\nSecond para here."
            await js(send({"type": "patch", "id": 5,
                     "fields": {"text": full, "streaming": False}}))
            await asyncio.sleep(0.05)
            r5 = await js("(()=>{const b=nodes.get(5).querySelector('[data-body]');"
                          "return {tc:b.textContent, n:b.children.length,"
                          " blockin:[...b.children].map(c=>"
                          "c.classList.contains('blockin'))};})()")

            print("  t1=%r t2=%r t4=%r" % (t1, t2, t4))
            print("  r3=%s r5=%s" % (json.dumps(r3, ensure_ascii=True),
                                     json.dumps(r5, ensure_ascii=True)))
            checks += [
                ("parrafo en curso oculto tras el 1er delta", t1.strip() == ""),
                ("mas texto sin cerrar: sigue oculto", t2.strip() == ""),
                ("al cerrar el parrafo se muestra el completo",
                 "Hello world." in r3["tc"] and r3["n"] == 1),
                ("el parrafo mostrado entra con fade (.blockin)",
                 r3["blockin"] == [True]),
                ("el 2o parrafo en curso no se muestra aun",
                 "Second" not in t4 and "Hello world." in t4),
                ("message_end muestra los dos parrafos",
                 "Hello world." in r5["tc"] and "Second para here." in r5["tc"]
                 and r5["n"] == 2),
                ("el ultimo parrafo entra con fade y el ya visto no",
                 r5["blockin"] == [False, True]),
                ("sin errores de consola", not p.problems),
            ]
    return checks


raise SystemExit(report(asyncio.run(main())))
