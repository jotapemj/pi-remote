"""/restart (pi_restart.py --cycle) no se lleva las tareas en segundo plano.

Mata el arbol del puente con taskkill, y en Windows una tarea lanzada
"separada" por pi sigue colgando de el. Con un arbol de procesos de verdad
(A = puente, B = pi, C = tarea en marcha, D = otro hijo de pi):
- con C apuntada como tarea en marcha: mueren A, B y D; C sigue viva;
- sin tareas: cae todo, como siempre (taskkill /T).
"""
import json
import os
import subprocess
import sys
import tempfile
import time

from harness import ROOT, report

sys.path.insert(0, str(ROOT))
import pi_restart as R              # noqa: E402
from pi_web_bridge import pid_alive  # noqa: E402

TREE = r'''
import json, os, subprocess, sys, time
role, out = sys.argv[1], sys.argv[2]
if role == "a":
    subprocess.Popen([sys.executable, __file__, "b", out])
else:
    sl = [sys.executable, "-c", "import time; time.sleep(120)"]
    c, d = subprocess.Popen(sl), subprocess.Popen(sl)
    with open(out, "w") as f:
        json.dump({"b": os.getpid(), "c": c.pid, "d": d.pid}, f)
time.sleep(120)
'''


def tree(tmp):
    script = os.path.join(tmp, "tree.py")
    out = os.path.join(tmp, "pids.json")
    with open(script, "w") as f:
        f.write(TREE)
    a = subprocess.Popen([sys.executable, script, "a", out])
    for _ in range(100):
        if os.path.exists(out) and os.path.getsize(out):
            break
        time.sleep(0.1)
    time.sleep(0.3)
    with open(out) as f:
        pids = json.load(f)
    pids["a"] = a.pid
    os.remove(out)
    return pids


def gone(pid):
    for _ in range(40):
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    return False


def main():
    tmp = tempfile.mkdtemp(prefix="pi-keep-")
    jobs = os.path.join(tmp, "jobs")
    os.makedirs(jobs)
    os.environ["PI_REMOTE_JOBS"] = jobs
    R.log = lambda msg: None              # sin tocar bridge-restart.log
    checks = []

    p = tree(tmp)
    with open(os.path.join(jobs, "1.json"), "w") as f:
        json.dump({"id": 1, "pid": p["c"], "status": "running",
                   "cwd": tmp, "command": "sleep"}, f)
    R.kill_tree(p["a"])
    dead = {k: gone(p[k]) for k in "abd"}
    alive_c = pid_alive(p["c"])
    print("  con tarea:", dead, "| tarea viva:", alive_c)
    checks += [
        ("el puente, pi y sus otros hijos caen", all(dead.values())),
        ("la tarea en segundo plano sigue viva", alive_c),
    ]
    subprocess.run(["taskkill", "/PID", str(p["c"]), "/F"],
                   capture_output=True)

    os.remove(os.path.join(jobs, "1.json"))
    p = tree(tmp)
    R.kill_tree(p["a"])
    dead = {k: gone(p[k]) for k in "abcd"}
    print("  sin tareas:", dead)
    checks.append(("sin tareas cae todo, como siempre", all(dead.values())))
    return checks


raise SystemExit(report(main()))
