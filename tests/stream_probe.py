"""Difusion: lo que se emite no puede ser el objeto vivo del puente.

`emit` no envia, ENCOLA en el loop de asyncio (run_coroutine_threadsafe).
Hasta que el loop serializa el payload, el hilo lector sigue sumando deltas al
mismo dict. Si se emite el item por referencia, la burbuja sale con texto de
mas y el cliente le vuelve a sumar los deltas que ya traia dentro:
"Entendido" -> "Entendidoendido". Se corregia solo al terminar el mensaje,
porque message_end manda el texto final entero por patch.

Aqui el encolado se modela sin hilos: se guarda el payload y se serializa
DESPUES de mutar, que es justo la ventana de la carrera.
"""
import json
from types import SimpleNamespace

from harness import report


def stub():
    """Lo justo de un Bridge para llamar a sus metodos de verdad."""
    s = SimpleNamespace(seq=0, log=[], produced=False, cwd="C:/proj",
                        state={"running": True, "tool": None}, queued=[])
    s.emit = s.queued.append            # encolado: aun sin serializar
    return s


def deliver(s):
    """El loop se pone al dia: serializa lo encolado, como haria el WebSocket."""
    return [json.loads(json.dumps(p)) for p in s.queued]


def backend():
    import pi_web_bridge as B
    checks = []

    # --- el caso del usuario, extremo a extremo del lado del puente ---
    DELTAS = ["Ent", "endido", ", voy a ello"]
    s = stub()
    cur = None
    for d in DELTAS:
        if cur is None:
            cur = B.Bridge.push(s, {"kind": "assistant", "text": d,
                                    "streaming": True})
        else:
            cur["text"] += d
            s.emit({"type": "delta", "id": cur["id"], "delta": d})
    # el cliente reconstruye: texto de la burbuja + suma de deltas
    seen = ""
    for m in deliver(s):
        if m["type"] == "item":
            seen = m["item"]["text"]
        else:
            seen += m["delta"]
    checks.append(("el cliente reconstruye el texto sin duplicar el arranque",
                   seen == "".join(DELTAS)))

    # --- la causa, aislada ---
    s = stub()
    it = B.Bridge.push(s, {"kind": "assistant", "text": "Ent"})
    it["text"] += "endido"
    checks += [
        # la identidad se mira en la cola: serializar ya rompe el alias
        ("lo encolado no es el objeto vivo del log",
         s.queued[0]["item"] is not s.log[-1]),
        ("sumar deltas tras push no toca lo ya emitido",
         deliver(s)[0]["item"]["text"] == "Ent"),
    ]

    # --- estado ---
    s = stub()
    B.Bridge.push_state(s)
    s.state["tool"] = "bash"
    checks.append(("el estado emitido es una copia",
                   deliver(s)[0]["state"]["tool"] is None))

    # --- snapshot: reconectar a mitad de turno ---
    s = stub()
    live = {"kind": "assistant", "text": "Ent", "id": 1}
    s.log.append(live)
    snap = B.Bridge.snapshot(s)
    live["text"] += "endido"
    s.state["running"] = False
    checks += [
        ("el snapshot copia los items en curso",
         json.loads(json.dumps(snap))["items"][0]["text"] == "Ent"),
        ("el snapshot copia el estado",
         json.loads(json.dumps(snap))["state"]["running"] is True),
    ]
    return checks


raise SystemExit(report(backend()))
