"""Los temas cubren los mismos tokens y todo se lee encima de su fondo."""
import io
import re

from harness import ROOT, report

html = io.open(ROOT / "static" / "index.html", encoding="utf-8").read()
COLOR = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def tokens(sel):
    m = re.search(re.escape(sel) + r"\{(.*?)\n\}", html, re.S)
    assert m, "no encuentro " + sel
    got = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1)))
    return {k: v.strip() for k, v in got.items() if COLOR.match(v.strip())}


THEMES = [("oscuro", tokens(":root")),
          ("claro", tokens(':root[data-theme="light"]')),
          ("klaude", tokens(':root[data-theme="klaude"]'))]

base = set(THEMES[0][1])
gaps = [(name, sorted(base ^ set(t))) for name, t in THEMES[1:]
        if set(t) != base]


def rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def lum(h):
    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = map(f, rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


PAIRS = [
    ("ink", "panel", "texto principal"),
    ("ink", "surface", "texto en tarjeta"),
    ("ink", "raise", "tu burbuja"),
    ("dim", "surface", "secundario"),
    ("dim", "deck", "barra de lectura"),
    ("faint", "surface", "pistas pequenas"),
    ("faint", "panel", "subtitulo"),
    ("amber", "panel", "acento"),
    ("amber", "deck", "acento en la barra"),
    ("amber", "surface", "acento en tarjeta"),
    ("amber", "raise", "etiqueta steer"),
    ("on-amber", "amber", "boton de enviar"),
    ("mint", "surface", "permitido"),
    ("coral", "surface", "denegado"),
    ("lit", "raise", "codigo en linea"),
    ("add", "box", "linea anadida"),
    ("del", "box", "linea quitada"),
    ("head-ink", "head", "cabecera de una caja"),
    ("box-ink", "box", "dentro de la caja"),
    ("field-ink", "panel", "lo que escribes"),
]

low = []
for name, theme in THEMES:
    print("\n" + name.upper())
    for fg, bg, what in PAIRS:
        f, b = "--" + fg, "--" + bg
        if f not in theme or b not in theme:
            continue
        r = ratio(theme[f], theme[b])
        flag = "ok " if r >= 4.5 else ("ui " if r >= 3.0 else "BAJO")
        if r < 3.0:
            low.append((name, fg, bg, round(r, 2)))
        print("  %-4s %5.2f  %-9s sobre %-8s %s" % (flag, r, fg, bg, what))

print()
if gaps:
    for name, diff in gaps:
        print("  descuadre en %s: %s" % (name, diff))
raise SystemExit(report([
    ("los tres temas cubren los mismos tokens", not gaps),
    ("nada por debajo de 3:1", not low),
]))
