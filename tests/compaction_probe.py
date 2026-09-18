"""Linea de compaction: el puente calcula el punto donde pi compacta
(ventana - reserva, merge global + proyecto confiado, como shouldCompact
de pi) y la barra lo dibuja como raya vertical sin texto."""
import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from harness import Bridge, Page, WS_URL, report

TMP = Path(tempfile.gettempdir()) / "compaction_probe_tmp"


class Area:
    def __enter__(self):
        shutil.rmtree(TMP, ignore_errors=True)
        TMP.mkdir(parents=True)
        return str(TMP)

    def __exit__(self, *a):
        shutil.rmtree(TMP, ignore_errors=True)


def backend():
    import pi_web_bridge as B
    checks = []

    class S:                # self minimo: solo state
        pass

    def compact(state):
        s = S()
        s.state = state
        B.Bridge.refresh_compact(s)
        return state["compactAt"]

    with Area() as td:
        B.AGENT_DIR = Path(td)
        st = lambda: {"context": {"window": 32768},
                      "projTrusted": False, "projSettings": {}}
        checks.append(("default: ventana - 16384",
                       compact(st()) == 32768 - 16384))

        (Path(td) / "settings.json").write_text(
            json.dumps({"compaction": {"reserveTokens": 8000}}),
            encoding="utf-8")
        checks.append(("global: ventana - 8000",
                       compact(st()) == 32768 - 8000))

        s = st()
        s["projTrusted"] = True
        s["projSettings"] = {"compaction": {"reserveTokens": 4000}}
        checks.append(("proyecto confiado gana al global",
                       compact(s) == 32768 - 4000))

        s = st()
        s["projTrusted"] = False
        s["projSettings"] = {"compaction": {"reserveTokens": 4000}}
        checks.append(("proyecto sin confianza no aplica",
                       compact(s) == 32768 - 8000))

        (Path(td) / "settings.json").write_text(
            json.dumps({"compaction": {"enabled": False}}),
            encoding="utf-8")
        checks.append(("compaction apagada: sin linea", compact(st()) is None))

        s = st()
        s["context"] = None
        checks.append(("sin ventana: sin linea", compact(s) is None))
    return checks


async def ui():
    checks = []
    with Area() as td:
        proj = Path(td) / "proj"
        proj.mkdir()
        with Bridge(extra={"PI_AGENT_DIR": td}):
            async with Page(port=9386) as p:
                js = p.js
                await p.go()
                # sin proyecto no hay pi: el puente descarta los stats
                await js("send({type:'open_project', path:%s})"
                         % json.dumps(str(proj)))
                await asyncio.sleep(1.5)
                # el cliente solo pide stats en turno; aqui se pide a mano
                await js("send({type:'get_session_stats'})")
                # fake_pi: ventana 32768, reserva default 16384 -> 50%
                ok = await js("""(async()=>{
                  for(let i=0;i<50;i++){
                    if(state.compactAt != null) return true;
                    await new Promise(r=>setTimeout(r,100));
                  }
                  return false;})()""")
                checks.append(("el estado trae compactAt", bool(ok)))
                left = await js("""(()=>{const m=$("#bar .cmk");
                  return m && getComputedStyle(m).display !== "none"
                     ? m.style.left : "hidden";})()""")
                checks.append(("la raya se dibuja al 50%", left == "50%"))
                await js("state.compactAt = null; paintCtx()")
                vis = await js("""getComputedStyle($("#bar .cmk")).display""")
                checks.append(("sin compactAt: raya oculta", vis == "none"))
    return checks


async def notes():
    """La nota del evento compaction_end. Exito: pinta «compacted» y baja el
    contexto. Fallo/abort (pi manda compaction_end SIN result: el evento
    session_compact_failed solo va a las extensiones): pinta un aviso warn con
    el motivo real y NO vacia la barra. El bug era tratar las tres formas como
    exito -> «compacted:  to  tokens» y contexto a None."""
    import websockets
    checks = []

    async def turn(ws, message, seconds=6.0):
        await ws.send(json.dumps({"type": "prompt", "message": message}))
        notes_by_id, ctxs = {}, []
        loop = asyncio.get_event_loop()
        end = loop.time() + seconds
        while True:
            rem = end - loop.time()
            if rem <= 0:
                break
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), rem))
            except asyncio.TimeoutError:
                break
            t = m.get("type")
            if t == "item" and (m.get("item") or {}).get("kind") == "note":
                it = m["item"]
                notes_by_id[it["id"]] = dict(it)
            elif t == "patch":
                notes_by_id.setdefault(m["id"], {}).update(m.get("fields") or {})
            elif t == "state":
                st = m.get("state") or {}
                if "context" in st:
                    ctxs.append(st.get("context"))
        return notes_by_id, ctxs

    td = tempfile.mkdtemp(prefix="compaction_notes_")   # dir propio, no el de ui()
    try:
        proj = Path(td) / "proj"
        proj.mkdir()
        with Bridge(extra={"PI_AGENT_DIR": td}):
            async with websockets.connect(WS_URL) as ws:
                await ws.recv()                       # snapshot inicial
                await ws.send(json.dumps({"type": "open_project",
                                          "path": str(proj)}))
                await asyncio.sleep(1.5)              # pi arranca

                # --- fallo: compaction_end sin result, con errorMessage ---
                fnotes, fctxs = await turn(ws, "compactfail ahora")
                cf = [n for n in fnotes.values()
                      if n.get("key") == "compact_failed"]
                blanked = any(isinstance(c, dict) and c.get("tokens") is None
                              for c in fctxs)
                real = any(isinstance(c, dict) and c.get("tokens")
                           for c in fctxs)
                print("  fallo: notas=%d compact_failed=%s blanked=%s"
                      % (len(fnotes), bool(cf), blanked))
                checks += [
                    ("el fallo pinta una nota compact_failed", len(cf) == 1),
                    ("la nota de fallo es warn, no info",
                     bool(cf) and cf[0].get("level") == "warn"),
                    ("la nota lleva el motivo real de pi",
                     bool(cf) and "Auto-compaction failed"
                     in (cf[0].get("text") or "")),
                    ("no queda una nota «compacted» fantasma",
                     not any(n.get("key") == "compacted"
                             for n in fnotes.values())),
                    ("el fallo NO vacia el contexto (nunca tokens None)",
                     real and not blanked),
                ]

                # --- exito: compaction_end con result, baja la barra ---
                snotes, sctxs = await turn(ws, "compact ahora")
                ok = [n for n in snotes.values()
                      if n.get("key") == "compacted"]
                dropped = any(isinstance(c, dict) and c.get("tokens") == 5200
                              for c in sctxs)
                print("  exito: compacted=%s bajo_a_5200=%s"
                      % (bool(ok), dropped))
                checks += [
                    ("el exito sigue pintando «compacted»", len(ok) == 1),
                    ("el exito baja el contexto a estimatedTokensAfter",
                     dropped),
                ]
    finally:
        shutil.rmtree(td, ignore_errors=True)
    return checks


async def main():
    out = backend() + await ui() + await notes()
    return out


if __name__ == "__main__":
    raise SystemExit(report(asyncio.run(main())))
