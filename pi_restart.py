#!/usr/bin/env python3
"""pi_restart.py — garantiza que haya exactamente un puente pi-remote.

Modos:
  --ensure      Si el puerto ya escucha, no hace nada; si no, arranca el
                puente y verifica. Es el modo de arranque en startup y de
                vigilancia periodica (idempotente).
  --cycle       Gracia fija (20 s por defecto), mata el arbol del puente,
                espera a que el puerto se libre, arranca uno nuevo y
                verifica. Lo dispara /restart a traves de tarea programada:
                la tarea corre bajo el servicio de Programador, FUERA del
                arbol de procesos del puente que mata (un matador hijo del
                puente muere con el). La gracia da tiempo a que la ultima
                respuesta del agente llegue al cliente antes del kill.
  --register    Crea/renueva la tarea one-shot "pi-remote-restart" que
                ejecuta este script con --cycle.

El log va a bridge-restart.log junto a este fichero. Diseñado para correr
bajo pythonw (sin consola): todo pasa por el log, no por stdout.
"""
import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("PI_WEB_PORT", "8770"))
LOG = HERE / "bridge-restart.log"
TASK_NAME = "pi-remote-restart"


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def port_alive():
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=1):
            return True
    except OSError:
        return False


def http_ok():
    try:
        return urllib.request.urlopen(
            "http://127.0.0.1:%d/" % PORT, timeout=2).getcode() == 200
    except Exception:
        return False


def pythonw():
    """pythonw si existe junto al interprete actual; sino, el propio."""
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return str(pyw if pyw.exists() else Path(sys.executable))


def port_owner():
    """El pid que escucha en PORT (el puente); None si nadie.

    Se apunta al dueño del puerto, NO a "cualquier python que parezca
    puente": un --cycle manual corriendo DENTRO de un puente no debe
    liquidar a los demas puentes (y el disparo real via tarea programada
    si que debe matar al suyo: el agente muere y vuelve con la sesion).
    """
    ps = ("Get-NetTCPConnection -LocalPort %d -State Listen "
          "-ErrorAction SilentlyContinue | "
          "Select-Object -First 1 -ExpandProperty OwningProcess" % PORT)
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True).stdout
    x = out.strip().split()
    return int(x[0]) if x and x[0].isdigit() else None


def kill_tree(pid):
    # Lista, sin shell: /PID y /T llegan a taskkill intactos.
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   capture_output=True, text=True)


def launch():
    DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    subprocess.Popen([pythonw(), str(HERE / "pi_web_bridge.py")],
                     cwd=str(HERE), creationflags=DETACHED)


def wait_port_free(seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        if not port_alive():
            return True
        time.sleep(0.5)
    return False


def wait_http(seconds=30):
    end = time.time() + seconds
    while time.time() < end:
        if http_ok():
            return True
        time.sleep(1)
    return False


def ensure():
    if port_alive():
        log("ensure: puerto %d ya escucha; no hago nada" % PORT)
        return 0
    log("ensure: sin puente; arrancando")
    launch()
    if wait_http():
        log("ensure: OK, el puente responde")
        return 0
    log("ensure: AVISO, el puerto no responde tras el arranque")
    return 1


def cycle(grace):
    owner = port_owner()
    if owner:
        log("cycle: gracia de %d s antes de matar el puerto %d (pid %s)"
            % (grace, PORT, owner))
        time.sleep(grace)
        kill_tree(owner)
        log("cycle: arbol del pid %s matado; esperando a que se libre" % owner)
        if not wait_port_free():
            # cobarde: no arrancar un segundo puente sobre un puerto ocupado
            log("cycle: AVISO, el puerto %d sigue ocupado; no arranco nada"
                % PORT)
            return 1
    else:
        log("cycle: nadie escucha en %d; arranco directo" % PORT)
    launch()
    if wait_http():
        log("cycle: OK, el puente nuevo responde")
        return 0
    log("cycle: AVISO, el puerto no responde tras el arranque")
    return 1


def register():
    """Tarea one-shot bajo la cuenta del usuario: sobrevive a la muerte de
    quien la dispara (el puente, o el agente dentro del puente)."""
    # sin gracia: el puente ya espera al agent_settled y da 2 s de telon
    tr = '"%s" "%s" --cycle --grace 0' % (pythonw(), str(HERE / "pi_restart.py"))
    r = subprocess.run(
        ["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/SC", "ONCE",
         "/ST", "00:00", "/TR", tr],
        capture_output=True, text=True)
    msg = "OK" if r.returncode == 0 else (r.stderr.strip() or r.stdout.strip())
    log("register: tarea %s -> %s" % (TASK_NAME, msg))
    return r.returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ensure", action="store_true")
    g.add_argument("--cycle", action="store_true")
    g.add_argument("--register", action="store_true")
    ap.add_argument("--grace", type=int,
                    default=int(os.environ.get("PI_RESTART_GRACE", "20")))
    a = ap.parse_args()
    if a.ensure:
        return ensure()
    if a.register:
        return register()
    return cycle(a.grace)


if __name__ == "__main__":
    raise SystemExit(main())
