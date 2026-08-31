"""Comprobaciones sobre el fichero, sin navegador."""
from harness import ROOT, report

import io
import re

h = io.open(ROOT / "static" / "index.html", encoding="utf-8").read()
css = h.split("</style>")[0]
body = h.split("</style>")[1]

checks = [
    ("barra oculta de verdad ([hidden] vencia a display:flex)",
     ".readout[hidden]{display:none}" in css),
    ("chips fuera del compositor",
     "rowbtns" not in h and 'class="chip' not in h),
    ("barra lateral con recientes",
     'id="rail"' in body and 'id="recents"' in body and ".rail.on{" in css),
    ("boton add project", 'id="addBtn"' in body and ".addp{" in css),
    ("hueco vacio centrado y pulsable",
     "left:50%; top:50%" in css and 'el.onclick = () => browse("")' in h),
    ("dialogo con fondo desenfocado", "backdrop-filter:blur(7px)" in css),
    ("help y about", "function helpModal()" in h and "function aboutModal()" in h),
    ("Jotapeveloper 2026", "Jotapeveloper 2026" in h),
    ("licencias de terceros",
     all(x in h for x in ("FastAPI", "BSD-3-Clause", "SIL Open Font License"))),
    ("paypal preparado", 'const PAYPAL = ""' in h),
    ("idioma en su propio dialogo",
     "function langModal(" in h and 'act("language"' in h),
    ("appearance sigue primero",
     h.index('head("appearance")') < h.index('act("language"')),
    ("palabra de estado junto al cursor",
     ".wordi{" in css and 'feed.querySelector(".wordi")' in h),
    ("cursor con latido suave", "@keyframes pulse{" in css),
    ("medidor de contexto redondeado",
     ".ctx{" in css and "border-radius:11px" in css
     and "p.toFixed(2)" in h),
    ("boton de copiar en los bloques",
     ".copyb{" in css and "legacyCopy(" in h),
    ("sitio para el teclado del movil",
     "var(--kb,0px)" in css and "visualViewport" in h),
    ("el nombre se funde al cambiar",
     ".plate h1 > span.out{opacity:0}" in css),
    ("fade entre palabras",
     ".wordi.out{opacity:0}" in css and "showWord(true)" in h),
    ("animacion de barra lateral",
     "cubic-bezier(.32,.72,0,1)" in css and "translateX(-101%)" in css),
    ("dialogo anima al abrir y cerrar",
     ".modal.open .mcard{transform:none}" in css
     and "visibility 0s linear .2s" in css),
    ("bottom sheet anima al abrir y cerrar",
     ".sheet.open .card{transform:none}" in css
     and "visibility 0s linear .22s" in css),
    ("animacion de mensajes", "@keyframes rise-in{" in css),
    ("un snapshot no anima 40 filas", ".nofx .turn{animation:none}" in css),
    ("boton stop en la barra", 'id="stopBtn"' in body and ".stopb{" in css),
    ("nombre de carpeta, no la ruta entera",
     "CWD.split(/[\\\\/]/)" in h),
    ("iconos material embebidos", "const ICONS = {" in h),
    ("sin svg dibujados a mano", "stroke-linecap" not in h),
    ("licencia apache citada", "Apache License 2.0" in h),
    ("un solo constructor de filas", "function pickBtn(" in h),
    ("icono por tipo de herramienta", "function toolIcon(" in h),
    ("nadie pisa la transicion del rail",
     ".rail,.segb{" not in css and "transition:transform .3s" in css),
    ("nadie pisa la del compositor",
     ",textarea,.segb{" not in css),
    ("paleta anima al abrir y cerrar",
     ".palette.open{" in css and "@keyframes rise{" not in css
     and "palette.hidden" not in h),
    ("enviar es un boton redondo con icono",
     'id="send" aria-label' in body and ".send .i{" in css),
    ("boton para bajar al final",
     'id="godown"' in body and ".godown.on{" in css),
    ("saltos de scroll instantaneos",
     'behavior:"instant"' in h),
    ("menu de la barra en dialogo",
     "function menuModal(" in h and ".mrow{" in css),
    ("borrado de sesion, moviendo a papelera",
     "delete_session" in h),
    ("marquee con degradado en los lados",
     "@keyframes mq{" in css and ".mq.run{" in css
     and "function marquee(" in h),
    ("boton de barra en el compositor",
     'id="slashBtn"' in body and ".field.typing .slashb{" in css),
]
root = re.search(r":root\{(.*?)\n\}", css, re.S).group(1)
dead = [t for t in re.findall(r"(--[\w-]+)\s*:", root)
        if ("var(%s)" % t) not in css]
classes = set(re.findall(r"^\.([a-z][\w-]*)", css, re.M))
dead_cls = sorted(c for c in classes if c not in body)

raise SystemExit(report(checks + [
    ("sin tokens huerfanos", not dead),
    ("sin clases sin uso", not dead_cls)]))
