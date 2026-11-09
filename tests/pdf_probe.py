"""Visor de PDF en la pestana Ficheros, con PDF.js servido por el puente.

Chrome en Android no pinta PDFs incrustados (los descarga): por eso PDF.js.
- /vendor/pdfjs sirve solo sus dos modulos, como JavaScript; nada mas.
- /api/file sirve el PDF (dentro del proyecto, con su tope).
- En la pagina: se cuentan las paginas, cada una se pinta en su canvas con
  su forma (la segunda es apaisada) y el color medido es el del PDF.
PDF fabricado aqui: dos paginas con un rectangulo de color, sin fuentes.
"""
import asyncio
import json
import os
import sys
import tempfile
import urllib.request

from harness import ROOT, URL, Bridge, FakeProject, Page, report

sys.path.insert(0, str(ROOT))
import pi_web_bridge as B          # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def make_pdf(path):
    """PDF minimo valido: pagina 1 vertical con un rectangulo rojo, pagina
    2 apaisada con uno azul. Tabla xref con los offsets reales."""
    pages = [(300, 400, b"1 0 0 rg 50 50 200 300 re f"),
             (500, 300, b"0 0 1 rg 40 40 420 220 re f")]
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            ("<< /Type /Pages /Kids [%s] /Count %d >>" % (
                " ".join("%d 0 R" % (3 + 2 * i) for i in range(len(pages))),
                len(pages))).encode()]
    for i, (w, h, ops) in enumerate(pages):
        objs.append(("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
                     "/Contents %d 0 R >>" % (w, h, 4 + 2 * i)).encode())
        objs.append(b"<< /Length %d >>\nstream\n" % len(ops) + ops
                    + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for n, body in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, x))
    with open(path, "wb") as f:
        f.write(out)


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.headers.get("Content-Type", ""), len(r.read())
    except urllib.error.HTTPError as e:
        return e.code, "", 0


def unit():
    with tempfile.TemporaryDirectory() as d:
        make_pdf(os.path.join(d, "doc.pdf"))
        rd = B.fs_read(d, "doc.pdf")
        img = B.fs_image(d, "doc.pdf")
        return [
            ("fs_read marca el PDF para el visor", rd.get("pdf") is True),
            ("/api/file lo entrega como application/pdf",
             bool(img) and img[1] == "application/pdf"
             and img[0].startswith(b"%PDF")),
        ]


async def in_page():
    checks = []
    with Bridge(), FakeProject() as proj:
        make_pdf(os.path.join(proj.path, "doc.pdf"))
        base = URL.split("/?")[0]   # sin el ?token de la pagina
        lib = get(base + "/vendor/pdfjs/pdf.min.mjs?v=1")
        wrk = get(base + "/vendor/pdfjs/pdf.worker.min.mjs?v=1")
        nope = [get(base + "/vendor/pdfjs/" + x)[0]
                for x in ("LICENSE-pdfjs.txt", "README.txt", "..%2Findex.html")]
        print("  vendor:", lib, wrk, nope)
        checks += [
            ("PDF.js se sirve desde el puente, como JavaScript",
             lib[0] == 200 and "javascript" in lib[1] and lib[2] > 100000
             and wrk[0] == 200 and wrk[2] > 100000),
            ("y nada mas de esa carpeta", all(c == 404 for c in nope)),
        ]
        async with Page() as p:
            js = p.js
            await p.go()
            await asyncio.sleep(0.8)
            await js("setLang('es'); send({type:'open_project', path:%s})"
                     % json.dumps(proj.path))
            for _ in range(40):
                if await js("state.cwd && !state.loading"):
                    break
                await asyncio.sleep(0.2)
            await js("openChanges('files'); openFile('doc.pdf')")
            got = None
            for _ in range(60):
                got = await js("""(() => {
                  const cs = [...document.querySelectorAll('.pdfp canvas')];
                  if(cs.length < 2) return null;
                  const px = c => { const b = c.getBoundingClientRect();
                    const d = c.getContext('2d').getImageData(
                      c.width >> 1, c.height >> 1, 1, 1).data;
                    return {w: Math.round(b.width), h: Math.round(b.height),
                            rgb: [d[0], d[1], d[2]]}; };
                  return {info: $('.pdfv').previousElementSibling.textContent,
                          pages: document.querySelectorAll('.pdfp').length,
                          p1: px(cs[0]), p2: px(cs[1])}; })()""")
                if got:
                    break
                await js("const b = $('#sheetBody'); b.scrollTop = b.scrollHeight")
                await asyncio.sleep(0.25)
            print("  visor:", got)
            if os.environ.get("PI_SHOT"):
                await js("$('#sheetBody').scrollTop = 0")
                await asyncio.sleep(0.4)
                await p.shot(os.environ["PI_SHOT"])
            ok = bool(got)
            checks += [
                ("cuenta las paginas", ok and got["info"] == "2 páginas"
                 and got["pages"] == 2),
                ("la primera se pinta, roja, vertical",
                 ok and got["p1"]["rgb"][0] > 200 and got["p1"]["rgb"][2] < 60
                 and got["p1"]["h"] > got["p1"]["w"]),
                ("la segunda, azul y apaisada",
                 ok and got["p2"]["rgb"][2] > 200 and got["p2"]["rgb"][0] < 60
                 and got["p2"]["w"] > got["p2"]["h"]),
                ("al ancho de la hoja",
                 ok and got["p1"]["w"] > 300),
            ]
            # salir del visor suelta el documento
            await js("goBack()")
            await asyncio.sleep(0.5)
            checks.append(("salir del visor suelta el PDF",
                           await js("pdfDoc === null")))
            problems = [x for x in p.problems if "favicon" not in x[1]]
            checks.append(("sin fallos en consola", not problems))
            if problems:
                print(problems[:4])
    return checks


async def main():
    return unit() + await in_page()


raise SystemExit(report(asyncio.run(main())))
