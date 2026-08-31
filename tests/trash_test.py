"""trash_session, con la raiz redirigida a un temporal: no toca ~/.pi"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

from harness import ROOT, report
import pi_web_bridge as B

tmp = Path(tempfile.mkdtemp(prefix="pi-trash-test-"))
B.sessions_root = lambda: tmp
proj = tmp / "--fake-project--"
proj.mkdir()

def make(name):
    f = proj / name
    f.write_text("{}\n", encoding="utf-8")
    return f

checks = []

a = make("a.jsonl")
why = B.trash_session(str(a), None)
moved = proj / "_trash" / "a.jsonl"
checks.append(("mueve a _trash",
               why == "" and moved.is_file() and not a.exists()))

b = make("a.jsonl")                       # mismo nombre otra vez
why = B.trash_session(str(b), None)
dup = list((proj / "_trash").glob("a*.jsonl"))
checks.append(("no pisa una que ya estaba",
               why == "" and len(dup) == 2))

c = make("open.jsonl")
why = B.trash_session(str(c), str(c))
checks.append(("no mueve la sesion abierta",
               why == "in_use" and c.is_file()))

why = B.trash_session(str(proj / "ghost.jsonl"), None)
checks.append(("avisa si no existe", why == "missing"))

outside = Path(tempfile.mkdtemp(prefix="pi-outside-")) / "x.jsonl"
outside.write_text("{}", encoding="utf-8")
why = B.trash_session(str(outside), None)
checks.append(("no sale de la carpeta de sesiones",
               why == "outside" and outside.is_file()))

why = B.trash_session(str(proj / "notes.txt"), None)
checks.append(("solo ficheros de sesion", why in ("missing", "outside")))

checks.append(("no lo cuenta como sesion",
               len(list(proj.glob("*.jsonl"))) == 1))

shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(outside.parent, ignore_errors=True)

raise SystemExit(report(checks))
