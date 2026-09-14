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
    ("paypal activo", 'const PAYPAL = "https://www.paypal.com/donate/' in h),
    ("los rotulos van en la sans, no en la mono",
     all(("%s{" % sel) not in css.replace(" ", "") or
         "var(--mono)" not in css.split(sel + "{")[1].split("}")[0]
         for sel in (".shead", ".sizecard .lbl", ".ask .cap"))
     and "var(--sans)" in css.split(".sheet h2{")[1].split("}")[0]),
    ("el menu navega por paginas",
     "function paintSheet(" in h and "function turnTo(" in h
     and 'id="sheetBack"' in body),
    ("apariencia va antes que idioma",
     h.index('act("appearance"') < h.index('act("language"')),
    ("entra y sale por lados distintos",
     "#sheetBody.to-left{" in css and "#sheetBody.to-right{" in css),
    ("palabra de estado en la barra, solo al pensar",
     ".rword{" in css and ".readout.thinking .rword" in css
     and 'id="rword"' in body),
    ("sin cursor parpadeante en la burbuja",
     ".cursor{" not in css and "@keyframes pulse{" not in css
     and '<span class="cursor">' not in h),
    ("la toolbar usa la fuente de los proyectos (sans)",
     ".plate h1{\n  font:600 15px/1.2 var(--sans)" in css),
    ("movement: revelado por caracter con interruptor",
     "function scheduleReveal" in h and "function fadeTail" in h
     and "setMotion(" in h),   # ya no es segmentado: es un switch on/off
    ("la card Movement es un interruptor fade/instant",
     'T("movement")' in h and '"fade" : "instant"' in h),
    ("hechos y fallidos nacen plegados; solo corriendo abre",
     'const open = !done ?' in h),
    ("el pensamiento no lleva boton de copiar",
     ".think .copyb{display:none}" in css),
    ("los botones de la toolbar no llevan caja",
     ".plate .iconbtn{border:none;" in css),
    ("el compositor tiene su linea de modelo/razonamiento",
     ".cmeta{" in css and 'id="cmeta"' in body),
    ("el enviar mide igual que el circulo de comando (sin override 46px)",
     ".send{width:46px" not in css),
    ("el compositor es editable y el enviar vive dentro de la caja",
     '<div id="box"' in body and 'contenteditable="true"' in body
     and body.index('<button class="send" id="send"')
         > body.index('<div id="box"')),
    ("el dialogo sobre la hoja lleva su propio velo y oscurece",
     "#sheet.open ~ .modal" not in css),
    ("el interruptor usa el acento del tema",
     '.sw[aria-checked="true"]{background:var(--amber)}' in css),
    ("la barra lateral se anima en escritorio",
     "transition:width .3s cubic-bezier(.32,.72,0,1)" in css),
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
     ".rword.out{opacity:0" in css and "showWord(true)" in h),
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
    ("enviar y parar comparten boton",
     'class="ic go"' in body and 'class="ic halt"' in body
     and ".send.halting" in css),   # el selector puede ir agrupado con summing
    ("nombre de carpeta, no la ruta entera",
     "CWD.split(/[\\\\/]/)" in h),
    ("version en un solo sitio",
     (ROOT / "version.txt").is_file()
     and 'state.version' in h and "VERSION" in
     io.open(ROOT / "pi_web_bridge.py", encoding="utf-8").read()),
    ("iconos material embebidos", "const ICONS = {" in h),
    ("sin svg dibujados a mano", "stroke-linecap" not in h),
    ("licencia apache citada", "Apache License 2.0" in h),
    ("un solo constructor de filas", "function pickBtn(" in h),
    ("icono por tipo de herramienta", "function toolIcon(" in h),
    ("nadie pisa la transicion del rail",
     ".rail,.segb{" not in css and "transition:transform .3s" in css),
    ("nadie pisa la del compositor",
     ",#box,.segb{" not in css),
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
    ("boton '+' que abre el popup de comandos e imagen",
     'id="slashBtn"' in body and 'id="plusMenu"' in body
     and ".plusmenu{" in css and 'data-act="image"' in body),
    ("la app no hace pinch-zoom (viewport bloqueado)",
     "user-scalable=no" in h),
    ("el lightbox amplia con X y gestos propios",
     'id="lbClose"' in body and ".lbx{" in css
     and "function openLightbox" in h and 'touch-action:none' in css),
]
root = re.search(r":root\{(.*?)\n\}", css, re.S).group(1)
dead = [t for t in re.findall(r"(--[\w-]+)\s*:", root)
        if ("var(%s)" % t) not in css]
classes = set(re.findall(r"^\.([a-z][\w-]*)", css, re.M))
dead_cls = sorted(c for c in classes if c not in body)

# una regla que se traga el @media de al lado se descarta entera y en
# silencio: el bloque de accesibilidad llevaba cinco versiones muerto
fused = [l.strip()[:60] for l in css.splitlines()
         if re.match(r"^[^@/*\s].*@(media|supports|keyframes)", l)]

# paridad i18n: cada tabla traduce las mismas claves en todos los idiomas;
# una clave ausente cae en silencio al ingles y nadie lo nota
langs = re.findall(r"const LANGS = \[(.*?)\]", h)[0]
lngs = [x.strip().strip('"') for x in langs.split(",")]

def lang_block(objname, lg):
    i = h.index("const %s" % objname)
    j = i
    while True:                       # la entrada real lleva { o , delante
        j = h.index(lg + ":", j)
        if h[:j].rstrip().endswith(("{", ",")):
            break
        j += 1
    k = j + len(lg) + 1
    open_c, close_c = ("[", "]") if h[k] == "[" else ("{", "}")
    depth = 0
    for m in range(k, len(h)):
        if h[m] == open_c:
            depth += 1
        elif h[m] == close_c:
            depth -= 1
            if not depth:
                break
    return h[k + 1:m]

def keys_of(block):
    # vacia el contenido de las cadenas antes de buscar claves: un valor que
    # acaba en ':' (p.ej. un titulo) no debe confundirse con una clave nueva
    stripped = re.sub(r'"(?:[^"\\]|\\.)*"', '""', block)
    return set(re.findall(r'(\w+):""', stripped))

i18n = []
for obj in ("STR", "NOTES", "XS", "XW"):
    base = keys_of(lang_block(obj, "en"))
    for lg in lngs:
        i18n.append(("%s.%s traduce las mismas %d claves que en"
                     % (obj, lg, len(base)),
                     keys_of(lang_block(obj, lg)) == base))
for lg in lngs:
    n = len(re.findall(r'"[\w\u4e00-\u9fff][^"\\]*"',
                       lang_block("WORDS", lg)))
    i18n.append(("WORDS.%s trae %d palabras de estado (>=50)" % (lg, n),
                 n >= 50))

raise SystemExit(report(checks + i18n + [
    ("ningun selector se traga una arroba", not fused),
    ("sin el flash azul del navegador al tocar",
     "-webkit-tap-highlight-color:transparent" in css),
    ("la barra del compositor se difumina por los lados",
     "footer::before{" in css and "mask-image:linear-gradient(to right"
     in css and "footer > *{position:relative" in css),
    ("el bloque de movimiento reducido sigue vivo",
     "@media (prefers-reduced-motion:reduce){\n  *{animation:none" in css),
    ("sin tokens huerfanos", not dead),
    ("sin clases sin uso", not dead_cls)]))
