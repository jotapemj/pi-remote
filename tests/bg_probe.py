"""Tareas en segundo plano (extensions/background.ts), probadas con Node de
verdad: los comandos corren en el bash de pi y el `pi` es falso (bg_ext.mjs).
Permiso, codigo de salida, salida limpia, aviso y despertar, tope de
despertares y de tareas, parar, aislamiento por proyecto y retomar tras un
reinicio de pi. Sin modelo."""
import json
import os
import shutil
import subprocess
import sys

from harness import ROOT, report

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def pi_pkg():
    npm = os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules")
    p = os.path.join(npm, "@earendil-works", "pi-coding-agent")
    return p if os.path.isdir(p) else None


def main():
    pkg, node = pi_pkg(), shutil.which("node")
    if not (pkg and node):
        return [("hay node y pi instalados", False)]
    r = subprocess.run([node, "tests/bg_ext.mjs"], cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=170,
                       env=dict(os.environ, PI_PKG=pkg))
    if r.stderr.strip():
        print(r.stderr.strip()[-2000:])
    try:
        checks = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print(r.stdout[-1500:])
        return [("la prueba de la extension termina y responde", False)]
    return [(n, ok) for n, ok in checks]


raise SystemExit(report(main()))
