"""quick_label no muestra el nombre viejo cuando el rename quedo enterrado.

pi anota cada rebautizado al final del .jsonl; en una sesion activa el rename
puede quedar a megas del borde. La ventana de cola de quick_label no basta
sola: si no ve session_info y el fichero pasa de la ventana, cae al pase
completo (como el arbol, session_label) en vez del nombre de creacion.
"""
import json
import shutil
import sys

from harness import ROOT, report

sys.path.insert(0, str(ROOT))
import pi_web_bridge as B          # noqa: E402

TMP = ROOT / "tests" / "_label_tmp"


def make(name, pad_after):
    TMP.mkdir(exist_ok=True)
    p = TMP / (name + ".jsonl")
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "message", "message": {
            "role": "user", "content": "Mensaje inicial viejo"}}) + "\n")
        f.write(json.dumps({"type": "session_info",
                            "name": "Nombre Nuevo"}) + "\n")
        pad = json.dumps({"type": "message", "message": {
            "role": "assistant", "content": "x" * 200}}) + "\n"
        w = 0
        while w < pad_after:
            f.write(pad)
            w += len(pad)
    return p


try:
    near = make("near", 1000)                 # rename a ~1 KB del final
    buried = make("buried", 2_000_000)         # rename a ~2 MB del final
    checks = [
        ("rename cerca del final: el nombre nuevo",
         B.quick_label(near) == "Nombre Nuevo"),
        ("rename enterrado a 2 MB: tambien el nuevo, no el viejo",
         B.quick_label(buried) == "Nombre Nuevo"),
        ("coincide con el arbol (session_label)",
         B.session_label(buried) == "Nombre Nuevo"),
    ]
finally:
    shutil.rmtree(TMP, ignore_errors=True)

raise SystemExit(report(checks))
