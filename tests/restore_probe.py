"""Restauracion al arrancar: la sesion guardada vuelve si sigue viva en su sitio."""
import tempfile
from pathlib import Path

from harness import report
import pi_web_bridge as B

tmp = Path(tempfile.mkdtemp(prefix="pi-restore-"))
B.sessions_root = lambda: tmp
B.STATE_FILE = tmp / "state.json"

# proyecto ficticio con su carpeta de sesiones (slug normalizado)
proj = "C:/fake/proj"
sdir = tmp / B._norm(proj)
sdir.mkdir(parents=True)
assert B.session_dir(proj) == sdir, "session_dir no encontro la carpeta"

f = sdir / "sesion.jsonl"
f.write_text("{}\n", encoding="utf-8")

checks = []

# 1. persist + last_session: la sesion guardada vuelve
B.persist(proj, str(f))
checks.append(("la sesion guardada se restaura", B.last_session(proj) == str(f)))

# 2. fichero borrado o a la basura: no se restaura
f.unlink()
checks.append(("sesion borrada: cae a una nueva", B.last_session(proj) is None))
f.write_text("{}\n", encoding="utf-8")

# 3. sesion de otra carpeta: no se mezcla con esta
other = tmp / B._norm("C:/fake/otro")
other.mkdir()
g = other / "ajena.jsonl"
g.write_text("{}\n", encoding="utf-8")
B.persist(proj, str(g))
checks.append(("sesion de otro proyecto: se rechaza", B.last_session(proj) is None))

# 4. cambiar de recientes no pisa la sesion guardada
B.persist(proj, str(f))
B.remember("C:/fake/otro")
checks.append(("los recientes no pisan la sesion",
               B.read_state().get("session") == str(f)))

report(checks)
