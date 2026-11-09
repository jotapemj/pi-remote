"""Zoom del visor de PDF: pellizco en tactil; botones y Ctrl+rueda con raton.

El viewport bloquea el zoom del navegador (user-scalable=no): el zoom es
nuestro. Se mide con gestos de verdad (Input.dispatch* de DevTools):
- pellizco: el zoom sube, el transform de la vista previa se quita al
  soltar y el punto del PDF bajo los dedos sigue bajo los dedos;
- tras parar, las paginas se repintan nitidas (canvas a la nueva escala);
- con raton salen los botones (en tactil no): + acerca, % vuelve al ancho;
  Ctrl+rueda acerca hacia el cursor;
- PDF largo a x4: las paginas lejanas se sueltan (memoria).
"""
import asyncio
import json
import os
import sys

from harness import Bridge, FakeProject, Page, report

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def make_pdf(path, n):
    """n paginas verticales con un rectangulo de color, sin fuentes."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            ("<< /Type /Pages /Kids [%s] /Count %d >>" % (
                " ".join("%d 0 R" % (3 + 2 * i) for i in range(n)),
                n)).encode()]
    for i in range(n):
        ops = (b"%.1f 0.2 0.6 rg 30 30 240 340 re f" % (i / max(1, n - 1)))
        objs.append(("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] "
                     "/Contents %d 0 R >>" % (4 + 2 * i)).encode())
        objs.append(b"<< /Length %d >>\nstream\n" % len(ops) + ops
                    + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for k, body in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % k + body + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, x))
    with open(path, "wb") as f:
        f.write(out)


STATE = """(() => { const b = $('#sheetBody'), w = b.querySelector('.pdfv');
  const c = w && w.querySelector('.pdfp canvas');
  const z = $('.pzoom');
  return {z: pdfZ, tf: w ? w.style.transform : null,
          ww: w ? Math.round(w.getBoundingClientRect().width) : 0,
          bw: Math.round(b.clientWidth),
          cw: c ? c.width : 0, dpr: devicePixelRatio,
          lbl: z ? z.querySelector('.pzl').textContent : null,
          btns: z ? getComputedStyle(z).display !== 'none' : false,
          drawn: w ? w.querySelectorAll('.pdfp canvas').length : 0}; })()"""

# coordenadas del PDF (en px de .pdfv sin zoom) bajo un punto de pantalla
UNDER = """((x, y) => { const w = $('#sheetBody .pdfv').getBoundingClientRect();
  return [(x - w.left) / pdfZ, (y - w.top) / pdfZ]; })"""


async def open_pdf(p, proj, name):
    js = p.js
    await p.go()
    await asyncio.sleep(0.8)
    await js("setLang('es'); send({type:'open_project', path:%s})"
             % json.dumps(proj.path))
    for _ in range(40):
        if await js("state.cwd && !state.loading"):
            break
        await asyncio.sleep(0.2)
    await js("openChanges('files'); openFile(%s)" % json.dumps(name))
    for _ in range(60):
        if await js("!!document.querySelector('.pdfp canvas')"):
            break
        await asyncio.sleep(0.2)
    await asyncio.sleep(0.6)


async def touch(p, kind, pts):
    await p.cmd("Input.dispatchTouchEvent", type=kind, touchPoints=[
        {"x": x, "y": y, "id": i} for i, (x, y) in enumerate(pts)])


async def mobile(proj):
    checks = []
    async with Page() as p:
        await p.cmd("Emulation.setTouchEmulationEnabled", enabled=True,
                    maxTouchPoints=5)
        await open_pdf(p, proj, "doc.pdf")
        s0 = await p.js(STATE)
        print("  tactil, antes:", s0)
        checks.append(("en tactil no hay botones de zoom",
                       s0["z"] == 1 and not s0["btns"]))
        # pellizco: dos dedos alrededor de un punto, separandose
        cx, cy = 200, 600
        before = await p.js(UNDER + "(%d, %d)" % (cx, cy))
        await touch(p, "touchStart", [(cx - 40, cy), (cx + 40, cy)])
        for k in range(1, 9):
            d = 40 + k * 5
            await touch(p, "touchMove", [(cx - d, cy), (cx + d, cy)])
            await asyncio.sleep(0.03)
        mid = await p.js(STATE)
        await touch(p, "touchEnd", [])
        await asyncio.sleep(0.15)
        s1 = await p.js(STATE)
        after = await p.js(UNDER + "(%d, %d)" % (cx, cy))
        print("  durante:", mid["tf"], "| tras soltar:", s1)
        print("  punto bajo los dedos: %s -> %s" % (before, after))
        checks += [
            ("durante el pellizco, vista previa con transform",
             (mid["tf"] or "").startswith("scale(")),
            ("al soltar: zoom ~2x y sin transform",
             1.8 <= s1["z"] <= 2.2 and not s1["tf"]),
            ("la vista se ensancha con el zoom",
             abs(s1["ww"] - s1["bw"] * s1["z"]) <= 3),
            ("el punto del PDF bajo los dedos sigue ahi",
             abs(before[0] - after[0]) < 4 and abs(before[1] - after[1]) < 4),
        ]
        await asyncio.sleep(0.8)
        s2 = await p.js(STATE)
        checks.append(("tras parar, se repinta nitido a la nueva escala",
                       s2["cw"] >= s2["ww"] * s2["dpr"] * 0.95))
        if os.environ.get("PI_SHOT"):
            await p.shot(os.environ["PI_SHOT"])
    return checks


async def desktop(proj):
    checks = []
    async with Page(width=1200, height=900, mobile=False) as p:
        await open_pdf(p, proj, "doc.pdf")
        s0 = await p.js(STATE)
        checks.append(("con raton salen los botones, a 100%",
                       s0["btns"] and s0["lbl"] == "100%"))
        await p.js("$('.pzoom [data-z=\"+\"]').click()")
        await p.js("$('.pzoom [data-z=\"+\"]').click()")
        await asyncio.sleep(0.3)
        s1 = await p.js(STATE)
        print("  raton, + + :", s1)
        checks.append(("+ acerca, con su porcentaje",
                       abs(s1["z"] - 1.56) < 0.02 and s1["lbl"] == "156%"))
        await p.js("$('.pzoom .pzl').click()")
        await asyncio.sleep(0.3)
        s2 = await p.js(STATE)
        checks.append(("el % vuelve al ancho de la hoja",
                       s2["z"] == 1 and s2["lbl"] == "100%"
                       and abs(s2["ww"] - s2["bw"]) <= 2))
        # Ctrl+rueda sobre la pagina
        box = await p.js("(() => { const r = $('.pdfp').getBoundingClientRect();"
                         " return [r.left + r.width / 2, r.top + 100]; })()")
        await p.cmd("Input.dispatchMouseEvent", type="mouseWheel",
                    x=box[0], y=box[1], deltaX=0, deltaY=-200, modifiers=2)
        await asyncio.sleep(0.3)
        s3 = await p.js(STATE)
        print("  ctrl+rueda:", s3["z"], s3["lbl"])
        checks.append(("Ctrl+rueda acerca", s3["z"] > 1.3))
        problems = [x for x in p.problems if "favicon" not in x[1]]
        checks.append(("raton: sin fallos en consola", not problems))
        if problems:
            print(problems[:4])
    return checks


async def memory(proj):
    async with Page() as p:
        await open_pdf(p, proj, "long.pdf")
        await p.js("pdfZoomTo(4)")
        await asyncio.sleep(0.6)
        await p.js("const b = $('#sheetBody'); b.scrollTop = b.scrollHeight")
        for _ in range(20):
            await asyncio.sleep(0.2)
            st = await p.js("""(() => [...document.querySelectorAll('.pdfp')]
              .map(h => h.firstChild ? 1 : 0))()""")
            if st[-1]:
                break
        print("  pdf largo a x4, al final:", st)
        return [("a x4 se pinta lo visible y se suelta lo lejano",
                 st[-1] == 1 and st[0] == 0 and sum(st) < len(st))]


async def main():
    with Bridge(), FakeProject() as proj:
        make_pdf(os.path.join(proj.path, "doc.pdf"), 2)
        make_pdf(os.path.join(proj.path, "long.pdf"), 12)
        return (await mobile(proj)) + (await desktop(proj)) \
            + (await memory(proj))


raise SystemExit(report(asyncio.run(main())))
