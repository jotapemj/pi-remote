"""El "pi exited" falso al cambiar de proyecto o de sesion. stop_pi cierra el
pi viejo y espera a que salga; su lector ve EOF mientras el nuevo aun se
lanza (Popen tarda en Windows). Si el gen no ha subido todavia, el lector se
cree el del pi actual y pinta el error. Aqui el Popen lento se simula con
una espera fija, asi el caso no depende del reparto de hilos. Y una muerte
de verdad tiene que seguir avisando.
"""
import subprocess
import sys
import threading
import time
from collections import deque

from harness import report

import pi_web_bridge as B

# un "pi" que vive hasta que le cierran stdin, sin decir nada
IDLE = [sys.executable, "-c", "import sys; sys.stdin.read()"]


def bridge():
    b = B.Bridge.__new__(B.Bridge)     # sin __init__: no abre proyectos reales
    b.log, b.seq, b.state, b.gen = deque(), 0, {}, 0
    b.produced, b.proc, b.cur = False, None, None
    b.emit = lambda payload: None
    return b


def launch(b):
    b.proc = subprocess.Popen(IDLE, stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, encoding="utf-8")
    b.gen += 1
    t = threading.Thread(target=b.reader, args=(b.proc, b.gen), daemon=True)
    t.start()
    return t


def exited(b):
    return [i for i in b.log if i.get("key") == "pi_exited"]


def main():
    checks = []
    # cambio de proyecto: cerrar el viejo, Popen lento, lanzar el nuevo
    b = bridge()
    old = launch(b)
    b.stop_pi()
    old.join(timeout=5)
    time.sleep(0.5)                    # el Popen del pi nuevo, en Windows
    launch(b)
    time.sleep(0.2)
    checks.append(("cerrar a proposito no pinta 'pi exited'", not exited(b)))
    checks.append(("ni marca muerto al pi", b.state.get("alive") is not False))
    b.stop_pi()

    # muerte de verdad: el aviso sigue saliendo
    b = bridge()
    t = launch(b)
    b.proc.kill()
    t.join(timeout=5)
    checks.append(("una muerte real si avisa", len(exited(b)) == 1
                   and b.state.get("alive") is False))
    return checks


raise SystemExit(report(main()))
