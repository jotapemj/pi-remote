"""Los dos temas cubren los mismos tokens y todo se lee."""
from harness import ROOT

import re, sys, io

html = io.open(ROOT / "static" / "index.html", encoding="utf-8").read()

def tokens(sel):
    m = re.search(re.escape(sel) + r"\{(.*?)\n\}", html, re.S)
    assert m, "no encuentro " + sel
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1)))

dark = tokens(":root")
light = tokens(':root[data-theme="light"]')

COLOR = re.compile(r"^#[0-9a-fA-F]{3,8}$")
dc = {k: v.strip() for k, v in dark.items() if COLOR.match(v.strip())}
lc = {k: v.strip() for k, v in light.items() if COLOR.match(v.strip())}

missing = sorted(set(dc) - set(lc))
extra = sorted(set(lc) - set(dc))
print("tokens de color: oscuro %d, claro %d" % (len(dc), len(lc)))
print("sin equivalente claro:", missing or "ninguno")
print("solo en claro       :", extra or "ninguno")

def rgb(h):
    h = h.lstrip("#")
    if len(h) == 3: h = "".join(c * 2 for c in h)
    return [int(h[i:i+2], 16) / 255 for i in (0, 2, 4)]

def lum(h):
    def f(c): return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = map(f, rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def ratio(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)

PAIRS = [
    ("ink",   "panel",   "texto principal"),
    ("ink",   "surface", "texto en tarjeta"),
    ("ink",   "raise",   "tu burbuja"),
    ("amber", "raise",   "etiqueta steer"),
    ("dim",   "surface", "salida de herramienta"),
    ("dim",   "deck",    "barra de lectura"),
    ("faint", "surface", "pistas pequenas"),
    ("faint", "panel",   "subtitulo cabecera"),
    ("amber", "panel",   "acento sobre fondo"),
    ("amber", "deck",    "palabra de estado"),
    ("amber", "surface", "acento en tarjeta"),
    ("on-amber", "amber", "texto del boton send"),
    ("mint",  "surface", "permitido"),
    ("coral", "surface", "denegado"),
    ("lit",   "raise",   "codigo en linea"),
]
bad = 0
for theme, name in ((dc, "OSCURO"), (lc, "CLARO ")):
    print("\n" + name)
    for fg, bg, what in PAIRS:
        f, b = "--" + fg, "--" + bg
        if f not in theme or b not in theme: continue
        r = ratio(theme[f], theme[b])
        flag = "ok " if r >= 4.5 else ("ui " if r >= 3.0 else "BAJO")
        if r < 3.0: bad += 1
        print("  %-4s %5.2f  %-9s sobre %-8s %s" % (flag, r, fg, bg, what))

print("\nfuera de norma:", bad)
sys.exit(1 if (missing or bad) else 0)
