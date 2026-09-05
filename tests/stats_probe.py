"""Estadisticas por respuesta: el servidor las calcula y la pagina las
muestra. Los tokens vienen de pi; las velocidades las mide el puente.
Todo contra fake_pi, sin agente real.
"""
import asyncio
import json

from harness import Bridge, FakeProject, Page, WS_URL, report


async def from_bridge():
    """El puente arma las estadisticas de la respuesta."""
    import websockets
    out, stats = [], None
    with Bridge(), FakeProject() as proj:
        async with websockets.connect(WS_URL) as ws:
            await ws.recv()
            await ws.send(json.dumps({"type": "open_project",
                                      "path": proj.path}))
            await asyncio.sleep(1.4)
            await ws.send(json.dumps({"type": "prompt", "message": "hola"}))
            end = asyncio.get_event_loop().time() + 8
            while asyncio.get_event_loop().time() < end:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=6))
                s = (m.get("fields") or {}).get("stats") \
                    or (m.get("item") or {}).get("stats")
                if s:
                    stats = s
                if (m.get("type") == "state"
                        and not m["state"].get("running") and stats):
                    break
    print("  del puente: %s" % json.dumps(stats))
    out += [
        ("el puente arma las estadisticas", stats is not None),
        ("tokens que da pi: generados y prompt",
         stats and stats.get("output") == 240 and stats.get("input") == 12000),
        ("total y razonamiento",
         stats and stats.get("total") == 12270
         and stats.get("reasoning") == 30),
        ("velocidad de generacion, medida por reloj",
         stats and isinstance(stats.get("genTps"), (int, float))
         and stats["genTps"] > 0),
        ("velocidad de prefill, medida por reloj",
         stats and isinstance(stats.get("promptTps"), (int, float))
         and stats["promptTps"] > 0),
    ]
    return out


async def gen_rate():
    """El tk/s mide la VENTANA DE STREAMING (primer->ultimo token), no la cola
    tras el ultimo token. Antes, esa cola (pi finalizando, o un turno que penso
    y ejecuto comandos) hundia el rate a valores irreales (~2 tk/s).
    """
    import websockets
    stats = None
    with Bridge(), FakeProject() as proj:
        async with websockets.connect(WS_URL) as ws:
            await ws.recv()
            await ws.send(json.dumps({"type": "open_project",
                                      "path": proj.path}))
            await asyncio.sleep(1.4)
            await ws.send(json.dumps({"type": "prompt", "message": "genrate"}))
            end = asyncio.get_event_loop().time() + 12
            while asyncio.get_event_loop().time() < end:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
                s = (m.get("fields") or {}).get("stats") \
                    or (m.get("item") or {}).get("stats")
                if s:
                    stats = s
                if (m.get("type") == "state"
                        and not m["state"].get("running") and stats):
                    break
    g = stats and stats.get("genTps")
    gms = stats and stats.get("genMs")
    print("  genrate: output=%s genMs=%s genTps=%s"
          % (stats and stats.get("output"), gms, g))
    # 50 tokens en ~1s de streaming + 2s de cola. Bien: ~40-55 tk/s, genMs ~1s.
    # Con el bug (contando la cola): 50/3 ~ 17 tk/s, genMs ~3s.
    return [
        ("el tk/s ignora la cola tras el ultimo token",
         isinstance(g, (int, float)) and g > 30),
        ("el genMs es la ventana de streaming (~1s), no ~3s",
         isinstance(gms, int) and 0 < gms < 1800),
    ]


ST = {"input": 12000, "output": 240, "cacheRead": 40, "reasoning": 30,
      "total": 12270, "cost": 0, "promptMs": 500, "genMs": 800,
      "genTps": 18.3, "promptTps": 2130.5}


async def in_page():
    checks = []
    with Bridge():
        async with Page(port=9316) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")
            await js("feed.innerHTML=''; nodes.clear();"
                     " render({id:1, kind:'assistant', streaming:false,"
                     " text:'hecho', stats:%s}); paint();"
                     " state.running=false; placeActions();" % json.dumps(ST))
            await asyncio.sleep(0.3)
            acts = await js("[!!document.querySelector('.msgacts .copy'),"
                            " !!document.querySelector('.msgacts .stats'),"
                            " !!document.querySelector('.msgacts .copy svg')]")
            print("  iconos bajo la respuesta: %s" % acts)
            checks += [
                ("hay boton de copiar y de estadisticas",
                 acts[0] is True and acts[1] is True),
                ("con su icono", acts[2] is True),
            ]

            # abre la hoja
            await js("document.querySelector('.msgacts .stats').click()")
            await asyncio.sleep(0.4)
            sheet = await js("(() => {"
                             " const open = $('#statsheet')"
                             ".classList.contains('open');"
                             " const rows = [...document.querySelectorAll("
                             "'#statsBody .strow')].map(r =>"
                             " r.textContent.replace(/\\s+/g,' ').trim());"
                             " return [open, $('#statsTitle').textContent,"
                             "  !!$('#statsIcon svg'), rows];})()")
            print("  hoja: abierta=%s titulo=%r icono=%s"
                  % (sheet[0], sheet[1], sheet[2]))
            for r in sheet[3]:
                print("     %s" % r)
            body = " ".join(sheet[3])
            checks += [
                ("la hoja se abre", sheet[0] is True),
                ("con el titulo pedido",
                 sheet[1] == "Estadísticas de respuesta"),
                ("y un icono de material", sheet[2] is True),
                ("generacion: t/s y tokens en la misma fila",
                 any("18,3 tok/s" in r and "240 tokens" in r
                     for r in sheet[3])),
                ("prompt: t/s y tokens en la misma fila, con miles",
                 any("2130,5 tok/s" in r and "12.000 tokens" in r
                     for r in sheet[3])),
                ("la cache cuando la hay", "40 tokens" in body),
                ("y el total", "12.270 tokens" in body),
            ]

            # copiar la respuesta
            await js("$('#statsheet').classList.remove('open')")
            copied = await js("(async () => {"
                              " const ok = await copyText('probando copia');"
                              " return ok;})()")
            print("  copyText devuelve: %s" % copied)
            checks.append(("copyText no lanza y devuelve un booleano",
                           copied in (True, False)))
    return checks


async def main():
    return await from_bridge() + await gen_rate() + await in_page()


raise SystemExit(report(asyncio.run(main())))
