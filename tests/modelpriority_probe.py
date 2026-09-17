"""Cadena de prioridad del modelo: proyecto > puente > pi.

Si un proyecto (confiado) tiene su propio modelo en .pi/settings.json, pi lo
aplica al arrancar la sesion y el puente NO debe pisarlo con el default global.
Sin modelo de proyecto, el default global del puente sigue imponiendose. El
caso sin confianza se ignora: pi no lee los settings locales sin trust.
"""
import asyncio
import json
import tempfile
from pathlib import Path

from harness import Bridge, FakeProject, HERE, WS_URL, report


def backend():
    """project_default_model: solo si hay confianza Y las dos claves."""
    import pi_web_bridge as B
    checks = []
    with tempfile.TemporaryDirectory() as td:
        old = B.AGENT_DIR
        B.AGENT_DIR = Path(td)
        try:
            root = Path(td) / "proj"
            (root / ".pi").mkdir(parents=True)
            cfg = root / ".pi" / "settings.json"

            # sin decision de confianza -> None (pi ignora los settings)
            cfg.write_text(json.dumps({"defaultProvider": "local",
                                       "defaultModel": "qwen3-8b"}),
                           encoding="utf-8")
            checks.append(("sin confianza: None",
                           B.project_default_model(str(root)) is None))

            # confiado + las dos claves -> devuelve el modelo
            B.set_trust(str(root), True)
            got = B.project_default_model(str(root))
            checks.append(("confiado y configurado: devuelve el modelo",
                           got == {"provider": "local",
                                   "id": "qwen3-8b"}))

            # solo una de las dos claves -> None
            cfg.write_text(json.dumps({"defaultModel": "qwen3-8b"}),
                           encoding="utf-8")
            checks.append(("solo defaultModel: None",
                           B.project_default_model(str(root)) is None))

            # confianza explícita False -> None
            cfg.write_text(json.dumps({"defaultProvider": "local",
                                       "defaultModel": "qwen3-8b"}),
                           encoding="utf-8")
            B.set_trust(str(root), False)
            checks.append(("confianza False: None",
                           B.project_default_model(str(root)) is None))

            # carpeta sin .pi/settings.json -> None
            bare = Path(td) / "bare"
            bare.mkdir()
            B.set_trust(str(bare), True)
            checks.append(("sin settings.json: None",
                           B.project_default_model(str(bare)) is None))
        finally:
            B.AGENT_DIR = old
    return checks


async def _open_and_read(projpath):
    """Abre el proyecto y devuelve el modelId FINAL del estado. Se drena un
    rato: el set_model del default llega despues del primer get_state, asi que
    el primer modelId no es el definitivo."""
    import websockets
    async with websockets.connect(WS_URL) as ws:
        await ws.recv()                       # snapshot inicial
        await ws.send(json.dumps({"type": "open_project", "path": projpath}))
        mid = None
        for _ in range(80):
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), 1.5))
            except asyncio.TimeoutError:
                break                         # sin mensajes nuevos: se asento
            st = m.get("state") or {}
            if st.get("modelId"):
                mid = st["modelId"]
    return mid


async def e2e():
    """Contra pi falso: el default global es swift/swift-27b, pero el pi nace
    en qwen3-8b. Con modelo de proyecto (confiado) no se toca; sin el, el
    puente lo cambia al global."""
    checks = []
    sf = HERE / "_state_modelprio.json"
    sf.write_text(json.dumps({"model": {"provider": "swift",
                                        "id": "swift-27b"}}), encoding="utf-8")
    try:
        with tempfile.TemporaryDirectory() as td:
            agent = Path(td) / "agent"
            agent.mkdir()

            # escenario A: proyecto confiado con su propio modelo
            with FakeProject("prio-a") as pa:
                (Path(pa.path) / ".pi").mkdir()
                (Path(pa.path) / ".pi" / "settings.json").write_text(
                    json.dumps({"defaultProvider": "local",
                                "defaultModel": "qwen3-8b"}), encoding="utf-8")
                import pi_web_bridge as B
                old = B.AGENT_DIR
                B.AGENT_DIR = agent
                try:
                    B.set_trust(pa.path, True)
                finally:
                    B.AGENT_DIR = old
                with Bridge(state=sf, fresh=False,
                            extra={"PI_AGENT_DIR": str(agent)}):
                    mid = await _open_and_read(pa.path)
                    print("  A (modelo de proyecto): %r" % mid)
                    checks.append(("proyecto confiado con modelo: "
                                   "el global no se aplica",
                                   mid == "qwen3-8b"))

            # escenario B: proyecto sin modelo -> el global manda
            # (el Bridge de A borro sf al salir: se reescribe el default)
            sf.write_text(json.dumps({"model": {"provider": "swift",
                                                "id": "swift-27b"}}),
                          encoding="utf-8")
            with FakeProject("prio-b") as pb:
                with Bridge(state=sf, fresh=False,
                            extra={"PI_AGENT_DIR": str(agent)}):
                    mid = await _open_and_read(pb.path)
                    print("  B (sin modelo de proyecto): %r" % mid)
                    checks.append(("proyecto sin modelo: "
                                   "el default global se aplica",
                                   mid == "swift-27b"))
    finally:
        sf.unlink(missing_ok=True)
    return checks


async def main():
    return backend() + await e2e()


raise SystemExit(report(asyncio.run(main())))
