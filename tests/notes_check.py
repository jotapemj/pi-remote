"""Las notas del puente viajan como clave, y el cliente sabe decirlas todas."""
import io
import re

from harness import ROOT, report

html = io.open(ROOT / "static" / "index.html", encoding="utf-8").read()
py = io.open(ROOT / "pi_web_bridge.py", encoding="utf-8").read()

block = html[html.index("const NOTES = {"):html.index("function noteText")]
en = dict(re.findall(r'(\w+):"([^"]*)"',
                     block[block.index("en:{"):block.index("es:{")]))
es = dict(re.findall(r'(\w+):"([^"]*)"', block[block.index("es:{"):]))

# claves que emite el puente, incluidas las que arma sobre la marcha
keys = set(re.findall(r'self\.note\("(?:error|warn|info)", "(\w+)"', py))
keys.discard("del_")
keys |= {"del_" + w for w in re.findall(r'return "(\w+)"', py)}
keys |= {"del_ok"}
keys.discard("del_")

print("  claves del puente:", len(keys))
print("  plantillas: en=%d es=%d" % (len(en), len(es)))

holes = []
sample = {"err": "algo", "path": "C:/x", "cmd": "compact", "before": 31000,
          "after": 9000, "n": 1, "max": 3}
for name, tpl in list(en.items()) + list(es.items()):
    filled = re.sub(r"\{(\w+)\}", lambda m: str(sample.get(m.group(1), "")),
                    tpl)
    if re.search(r"\{\w+\}", filled):
        holes.append(name)

raise SystemExit(report([
    ("todas las del puente tienen plantilla", not (keys - set(en))),
    ("los dos idiomas cubren lo mismo", set(en) == set(es)),
    ("ninguna plantilla sobra", not (set(en) - keys)),
    ("ningun hueco sin rellenar", not holes),
]))
