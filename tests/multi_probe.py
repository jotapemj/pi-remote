"""Un turno con pasos de solo herramienta no deja burbujas vacias.

Antes, cada paso que solo lanzaba una herramienta creaba una burbuja de
asistente sin texto, con sus dos botones, y ademas partia el tramo de
herramientas. Ahora la burbuja nace con el primer token: sin token, sin
burbuja. Contra fake_pi (rama 'multi'), sin agente real.
"""
import asyncio
import json

from harness import Bridge, FakeProject, Page, WS_URL, report


async def from_bridge():
    """El puente no emite items de asistente vacios."""
    import websockets
    kinds = []
    with Bridge(), FakeProject() as proj:
        async with websockets.connect(WS_URL) as ws:
            await ws.recv()
            await ws.send(json.dumps({"type": "open_project",
                                      "path": proj.path}))
            await asyncio.sleep(1.4)
            await ws.send(json.dumps({"type": "prompt", "message": "multi"}))
            end = asyncio.get_event_loop().time() + 10
            settled = False
            texts = {}
            while asyncio.get_event_loop().time() < end and not settled:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=6))
                if m.get("type") == "item":
                    it = m["item"]
                    if it.get("kind") in ("assistant", "tool"):
                        kinds.append(it["kind"])
                        if it["kind"] == "assistant":
                            texts[it["id"]] = it.get("text", "")
                if m.get("type") == "patch":
                    f = m["fields"]
                    if "text" in f and m["id"] in texts:
                        texts[m["id"]] = f["text"]
                if m.get("type") == "state" and not m["state"].get("running"):
                    if kinds:
                        settled = True
    asis = [t for k, t in zip(kinds, [texts.get(i, "") for i in texts])]
    tools = kinds.count("tool")
    n_asis = kinds.count("assistant")
    empties = [t for t in texts.values() if not t.strip()]
    print("  items: %d asistente, %d herramienta" % (n_asis, tools))
    print("  textos asistente: %s" % list(texts.values()))
    return [
        ("solo las respuestas con texto son burbujas", n_asis == 2),
        ("ninguna burbuja de asistente esta vacia", empties == []),
        ("las tres herramientas siguen ahi", tools == 3),
    ]


# lo que el puente arreglado manda ahora: texto, tres tools, texto
SEQ = """
feed.innerHTML = ""; nodes.clear();
render({id:1, kind:"user", text:"multi"});
render({id:2, kind:"assistant", streaming:false, text:"Verifico cuando.",
        stats:{output:20,input:9000,total:9020,cacheRead:0,reasoning:0,
               cost:0,genTps:12,promptTps:9000}});
render({id:3, kind:"tool", name:"ctx_execute", status:"done",
        args:{code:"import os"}, output:"ok"});
render({id:4, kind:"tool", name:"ctx_execute", status:"done",
        args:{code:"import re"}, output:"ok"});
render({id:5, kind:"tool", name:"ctx_execute", status:"done",
        args:{code:"import sys"}, output:"ok"});
render({id:6, kind:"assistant", streaming:false, text:"Listo, era static.",
        stats:{output:30,input:9100,total:9130,cacheRead:0,reasoning:0,
               cost:0,genTps:13,promptTps:9100}});
paint();
"""


async def in_page():
    checks = []
    with Bridge():
        async with Page(port=9317) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")
            await js(SEQ)
            await js("state.running=false; placeActions()")
            await asyncio.sleep(0.35)
            r = await js("""(() => {
              const saids = [...document.querySelectorAll('.said')];
              return {
                said: saids.length,
                vacias: saids.filter(d => d.textContent.trim()==='').length,
                msgacts: document.querySelectorAll('.msgacts').length,
                actsEnUltima: (() => { const a =
                  [...document.querySelectorAll('.said')].pop();
                  return a && !!a.parentNode.querySelector('.msgacts'); })(),
                grupos: document.querySelectorAll('.toolgroup').length,
                enGrupo: document.querySelectorAll(
                          '.toolgroup .gbody .tool').length,
                rotulo: (document.querySelector('.toolgroup .gn')||{})
                          .textContent || "",
                sueltas: document.querySelectorAll(
                          '#feed > .turn > .tool').length,
              };
            })()""")
            print("  DOM: %s" % json.dumps(r, ensure_ascii=False))
            checks += [
                ("dos burbujas, ninguna vacia",
                 r["said"] == 2 and r["vacias"] == 0),
                ("un solo juego de botones, en la respuesta final",
                 r["msgacts"] == 1 and r["actsEnUltima"] is True),
                ("las tres herramientas en un solo grupo",
                 r["grupos"] == 1 and r["enGrupo"] == 3),
                ("con su rotulo", "3 comandos" in r["rotulo"]),
                ("y ninguna herramienta suelta", r["sueltas"] == 0),
            ]
    return checks


async def main():
    return await from_bridge() + await in_page()


raise SystemExit(report(asyncio.run(main())))
