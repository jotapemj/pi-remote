"""ask_user: el cuestionario de la extension propia. En RPC llega como UN
dialogo `editor` con titulo marcador y las preguntas en JSON en el prefill;
el puente lo emite como tarjeta `ask` con `quiz`. La tarjeta: una pregunta
por pagina, paginador, recomendada, descripcion, «otra cosa», omitir y
enviar (activo con todas contestadas). A pi vuelve JSON; al item, un
resumen. El interruptor de Functions lo guarda el puente (state.json) y el
pi siguiente arranca con -e. Contra fake_pi.
"""
import asyncio
import json
import sys
from collections import deque
from pathlib import Path

from harness import Bridge, FakeProject, Page, WS_URL, report

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def drain(ws, seconds):
    got = []
    end = asyncio.get_event_loop().time() + seconds
    while True:
        left = end - asyncio.get_event_loop().time()
        if left <= 0:
            break
        try:
            got.append(json.loads(await asyncio.wait_for(ws.recv(), left)))
        except asyncio.TimeoutError:
            break
    return got


QS = {"questions": [
    {"question": "Where?", "header": "Storage",
     "options": [{"label": "Phone"}, {"label": "Server"}]},
    {"question": "Extras?", "options": [{"label": "Covers"},
                                        {"label": "Stats"}]}]}


def history():
    """El historial rehace la tarjeta contestada desde la llamada y su
    resultado (details; o el texto, en sesiones de antes)."""
    import pi_web_bridge as B
    # sin construir un Bridge: su __init__ abre el ultimo proyecto del
    # state.json REAL y lanza un pi de verdad
    class Stub:
        state, log, seq, cur = {}, deque(), 0, None
        emit = staticmethod(lambda p: None)
        snapshot = staticmethod(lambda: {})
        load_history = B.Bridge.load_history
    b = Stub()
    call = lambda i: {"role": "assistant", "content": [
        {"type": "toolCall", "id": i, "name": "ask_user", "arguments": QS}]}
    b.load_history([
        call("a"),
        {"role": "toolResult", "toolCallId": "a", "toolName": "ask_user",
         "content": [{"type": "text", "text": "x"}],
         "details": {"answers": [{"selected": ["Phone"]}, {"skipped": True}]}},
        call("b"),
        {"role": "toolResult", "toolCallId": "b", "toolName": "ask_user",
         "content": [{"type": "text", "text":
                      "Q1 (Storage): user selected: Server; user wrote: NAS\n"
                      "Q2 (Extras?): user selected: Covers, Stats"}]},
        call("c"),
        {"role": "toolResult", "toolCallId": "c", "toolName": "ask_user",
         "content": [{"type": "text", "text": "dismissed"}],
         "details": {"cancelled": True}},
        call("d")])                            # sin resultado: se corto
    asks = [i for i in b.log if i.get("kind") == "ask"]
    return [
        ("historial: ask_user sin fila de herramienta",
         not any(i.get("kind") == "tool" for i in b.log)),
        ("historial: tres tarjetas, la cortada fuera", len(asks) == 3),
        ("respuestas desde details",
         asks and asks[0]["quizAnswers"] == [{"selected": ["Phone"]},
                                             {"skipped": True}]),
        ("respuestas desde el texto (sesiones viejas)",
         len(asks) > 1 and asks[1]["quizAnswers"] == [
             {"selected": ["Server"], "other": "NAS"},
             {"selected": ["Covers", "Stats"]}]),
        ("cerrada sin contestar: cancelada",
         len(asks) > 2 and asks[2].get("cancelled") is True),
    ]


def unit():
    import pi_web_bridge as B
    good = B.quiz_questions(json.dumps({"questions": [
        {"question": "Q?", "options": [{"label": "a"}, {"label": ""},
                                       "junk"], "recommended": 1},
        {"no": "question"}] + [{"question": "x", "options": []}] * 5}))
    return [
        ("el saneado descarta opciones vacias y basura",
         good[0]["options"] == [{"label": "a", "description": ""}]),
        ("y preguntas sin texto; tope de 4", len(good) == 4),
        ("prefill que no es JSON: no es cuestionario",
         B.quiz_questions("hola") is None),
    ]


CARD = """(() => { const c = document.querySelector('.ask.quiz');
  if(!c) return null;
  return {cap: c.querySelector('.cap').textContent,
          pager: (c.querySelector('.qpager span') || {}).textContent || '',
          q: c.querySelector('h3').textContent,
          opts: [...c.querySelectorAll('.qopt .ql')].map(x => x.textContent),
          sel: [...c.querySelectorAll('.qopt')].map(x => x.classList.contains('sel')),
          desc: [...c.querySelectorAll('.qopt .qd')].map(x => x.textContent),
          rec: [...c.querySelectorAll('.qrec')].length,
          send: c.querySelector('.qsend').disabled}; })()"""


async def card(js):
    """Espera a que la tarjeta nueva este pintada (el turno anterior asienta
    antes de que el fake atienda el prompt siguiente)."""
    for _ in range(50):
        if await js("!!document.querySelector('.ask.quiz')"):
            return True
        await asyncio.sleep(0.1)
    return False


async def e2e():
    import websockets
    checks = []
    with Bridge(), FakeProject() as proj:
        async with websockets.connect(WS_URL) as ws:
            await drain(ws, 0.5)
            await ws.send(json.dumps({"type": "open_project", "path": proj.path}))
            await drain(ws, 1.5)
            await ws.send(json.dumps({"type": "prompt", "message": "quiz"}))
            got = await drain(ws, 1.5)
            ask = next((m["item"] for m in got if m.get("type") == "item"
                        and m["item"].get("kind") == "ask"), None)
            checks += [
                ("en vivo, ask_user no pinta fila de herramienta",
                 not any(m.get("type") == "item"
                         and m["item"].get("name") == "ask_user" for m in got)),
                ("el editor marcado llega como cuestionario",
                 ask is not None and len(ask.get("quiz") or []) == 2),
                ("titulo = la primera pregunta, sin comando colgado",
                 ask and ask["title"] == "Where are playlists stored?"
                 and not ask["tool"]),
            ]

            async with Page() as p:
                js = p.js
                await p.go()
                await asyncio.sleep(0.8)
                await js("setLang('en')")
                c1 = await js(CARD)
                print("  pagina 1:", c1)
                await js("document.querySelectorAll('.ask.quiz .qopt')[0].click()")
                await asyncio.sleep(0.5)
                c2 = await js(CARD)
                print("  pagina 2:", c2)
                await js("""(() => { const b = document.querySelectorAll('.ask.quiz .qopt');
                  b[0].click(); })()""")
                await asyncio.sleep(0.2)
                await js("document.querySelectorAll('.ask.quiz .qopt')[2].click()")
                await asyncio.sleep(0.2)
                c3 = await js(CARD)
                await js("""(() => { const i = document.querySelector('.ask.quiz .qother input');
                  i.value = 'Vinyl'; i.dispatchEvent(new Event('input')); })()""")
                back = await js("""(() => { document.querySelector('.ask.quiz .qpager .prev').click();
                  return [...document.querySelectorAll('.ask.quiz .qopt')]
                    .map(x => x.classList.contains('sel')); })()""")
                await js("document.querySelector('.ask.quiz .qsend').click()")
                after = await drain(ws, 1.5)
                await asyncio.sleep(0.3)
                note = next((m["item"]["text"] for m in after
                             if m.get("type") == "item"
                             and str(m["item"].get("text", "")).startswith("ui:")),
                            "")
                sent = json.loads(json.loads(note[3:])) if note else {}
                row = await js("""(() => { const d = document.querySelector('details.ask.done');
                  return d ? d.querySelector('.qans').textContent : null; })()""")
                inside = await js("""(() => { const d = document.querySelector('details.ask.done');
                  return {q: [...d.querySelectorAll('.qitem .qq')].map(x => x.textContent),
                          a: [...d.querySelectorAll('.qitem .qa')].map(x => x.textContent),
                          verdict: !!d.querySelector('.verdict')}; })()""")
                print("  dentro:", inside)
                print("  a pi:", sent, "| fila:", row)
                checks += [
                    ("pagina 1: cabecera, paginador y pregunta",
                     c1 and c1["cap"] == "Storage" and c1["pager"] == "1 / 2"
                     and c1["q"] == "Where are playlists stored?"),
                    ("opciones con descripcion y una recomendada",
                     c1 and c1["desc"] == ["Local Room database.",
                                           "Synced with the server."]
                     and c1["rec"] == 1 and "Phone only" in c1["opts"][0]),
                    ("enviar apagado sin contestar todo", c1 and c1["send"]),
                    ("elegir una opcion pasa a la siguiente",
                     c2 and c2["pager"] == "2 / 2" and c2["cap"] == "Extras"),
                    ("multiseleccion: varias a la vez y enviar se enciende",
                     c3 and c3["sel"] == [True, False, True] and not c3["send"]),
                    ("volver atras conserva lo elegido", back == [True, False]),
                    ("a pi llega JSON con todas las respuestas",
                     sent.get("answers") == [
                         {"selected": ["Phone only"]},
                         {"selected": ["Covers", "Stats"], "other": "Vinyl"}]),
                    ("la tarjeta se compacta con el resumen",
                     row is not None and "Phone only · Covers, Stats, Vinyl" in row),
                    ("abierta: cada pregunta con su respuesta, sin repetir el resumen",
                     inside["q"] == ["Where are playlists stored?", "Which extras?"]
                     and inside["a"] == ["Phone only", "Covers, Stats, Vinyl"]
                     and not inside["verdict"]),
                ]

                # omitir y cancelar
                await ws.send(json.dumps({"type": "prompt", "message": "quiz"}))
                await drain(ws, 0.3)
                await card(js)
                await js("""(() => { const c = [...document.querySelectorAll('.ask.quiz')].pop();
                  c.querySelector('[data-q=skip]').click(); })()""")
                await asyncio.sleep(0.5)
                await js("""(() => { const c = [...document.querySelectorAll('.ask.quiz')].pop();
                  c.querySelector('[data-q=skip]').click(); })()""")
                await asyncio.sleep(0.4)
                sk = await js("""(() => { const c = [...document.querySelectorAll('.ask.quiz')].pop();
                  const b = c.querySelector('.qsend'); const off = b.disabled;
                  b.click(); return off; })()""")
                after = await drain(ws, 1.5)
                note = next((m["item"]["text"] for m in after
                             if m.get("type") == "item"
                             and str(m["item"].get("text", "")).startswith("ui:")),
                            "")
                skipped = json.loads(json.loads(note[3:])) if note else {}
                checks.append(("omitir cuenta como respuesta y viaja como skipped",
                               sk is False and skipped.get("answers")
                               == [{"skipped": True}, {"skipped": True}]))

                await ws.send(json.dumps({"type": "prompt", "message": "quiz"}))
                await drain(ws, 0.3)
                await card(js)
                await js("""(() => { const c = [...document.querySelectorAll('.ask.quiz')].pop();
                  c.querySelector('[data-q=cancel]').click(); })()""")
                after = await drain(ws, 1.0)
                canc = any(m.get("type") == "patch"
                           and m.get("fields", {}).get("cancelled") for m in after)
                checks.append(("cancelar cierra el cuestionario como cancelado", canc))

                # el interruptor: lo guarda el puente, aplica al reiniciar
                await js("menuSheet(); goPage('functions')")
                await asyncio.sleep(0.6)
                await js("""[...document.querySelectorAll('#sheetBody .fcard')]
                  .find(c => c.textContent.includes('Ask the user'))
                  .querySelector('.sw').click()""")
                await asyncio.sleep(0.3)
                dlg = await js("[$('#modalTitle').textContent,"
                               " $('#modalExtra').hidden ? null : $('#modalExtra').textContent,"
                               " $('#modalOk').textContent]")
                await js("$('#modalOk').click()")
                st = await drain(ws, 0.8)
                on = [m["state"].get("askUser") for m in st if m.get("type") == "state"]
                checks += [
                    ("el interruptor pregunta, con Activate y Restart now",
                     dlg == ["Ask the user", "Restart now", "Activate"]),
                    ("encendido, el puente lo guarda", on and on[-1] is True),
                ]
                # puente sin reiniciar: rechaza y el interruptor no miente
                rej = await js("""(() => { const sw = $('#askUserSw');
                  sw.setAttribute('aria-checked', 'false');
                  onRpc({command:'ask_user_set', data:{error:'command not allowed'}});
                  return [sw.getAttribute('aria-checked'),
                          [...document.querySelectorAll('.note')].pop().textContent]; })()""")
                checks.append(("rechazado, el interruptor vuelve a lo del puente",
                               rej[0] == "true" and "not allowed" in rej[1]))
                # el siguiente pi arranca con la extension
                await ws.send(json.dumps({"type": "open_project",
                                          "path": str(Path(proj.path).parent)}))
                st = await drain(ws, 1.5)
                live = [m["state"].get("askUserLive") for m in st
                        if m.get("type") == "state"]
                checks.append(("el pi siguiente arranca con -e ask_user.ts",
                               live and live[-1] is True))
    return checks


async def main():
    return unit() + history() + await e2e()

raise SystemExit(report(asyncio.run(main())))
