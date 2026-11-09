"""Explorador de ficheros del proyecto: solo lectura y nunca fuera de la
carpeta.

- fs_resolve rechaza ../, rutas absolutas y otras unidades; fs_list oculta
  .git y node_modules y pone carpetas primero; fs_read da lineas, o dice
  binario / grande; las imagenes van por /api/file, que solo sirve
  imagenes (sin SVG) de dentro del proyecto.
- En la pagina: sin repo la hoja abre en Ficheros; tocar una carpeta entra,
  atras sube; un fichero se ve con numeros de linea; "anadir ruta" la deja
  en el compositor; una imagen se pinta.
"""
import asyncio
import base64
import json
import os
import sys
import tempfile

from harness import ROOT, Bridge, FakeProject, Page, report

sys.path.insert(0, str(ROOT))
import pi_web_bridge as B          # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def fill(d):
    def w(rel, data):
        fp = os.path.join(d, *rel.split("/"))
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode())
    w("main.py", "import os\n\ndef run():\n    return 1\n")
    w("src/util.py", "x = 1\n")
    w("Zeta.txt", "z\n")
    w("assets/logo.png", PNG)
    w("assets/icon.svg", "<svg xmlns='http://www.w3.org/2000/svg'/>")
    w("blob.bin", b"\x00\x01\x02")
    w(".git/config", "[core]\n")
    w("node_modules/x/index.js", "1\n")
    w("big.log", "a" * (B.FS_TEXT_MAX + 10))


def unit():
    with tempfile.TemporaryDirectory() as d:
        fill(d)
        outside = os.path.join(os.path.dirname(d), "fuera.txt")
        lst = B.fs_list(d, "")
        names = [e["name"] for e in lst.get("entries", [])]
        print("  raiz:", names)
        rd = B.fs_read(d, "main.py")
        return [
            ("carpetas primero, luego ficheros, sin distinguir mayusculas",
             names == ["assets", "src", "big.log", "blob.bin", "main.py",
                       "Zeta.txt"]),
            ("oculta .git y node_modules",
             ".git" not in names and "node_modules" not in names),
            ("subcarpeta con su ruta relativa",
             B.fs_list(d, "src").get("path") == "src"),
            ("../ no sale del proyecto", B.fs_resolve(d, "../fuera.txt") is None
             and "error" in B.fs_read(d, "../fuera.txt")),
            ("una ruta absoluta de fuera tampoco",
             B.fs_resolve(d, outside) is None
             and B.fs_resolve(d, "C:/Windows/win.ini") is None),
            ("lee un fichero en lineas",
             rd.get("lines") == ["import os", "", "def run():",
                                 "    return 1"]),
            ("binario: se dice", B.fs_read(d, "blob.bin").get("binary") is True),
            ("grande: se dice", B.fs_read(d, "big.log").get("big") is True),
            ("imagen: se marca para pedirla aparte",
             B.fs_read(d, "assets/logo.png").get("image") is True),
            ("la imagen sale como bytes con su tipo",
             B.fs_image(d, "assets/logo.png") == (PNG, "image/png")),
            ("SVG no se sirve", B.fs_image(d, "assets/icon.svg") is None),
            ("ni texto por /api/file", B.fs_image(d, "main.py") is None),
        ]


async def in_page():
    checks = []
    with Bridge(), FakeProject() as proj:
        fill(proj.path)
        async with Page() as p:
            js = p.js
            await p.go()
            await asyncio.sleep(0.8)
            await js("setLang('es'); send({type:'open_project', path:%s})"
                     % json.dumps(proj.path))
            for _ in range(40):
                if await js("!$('#changesBtn').hidden && state.cwd"):
                    break
                await asyncio.sleep(0.2)
            await asyncio.sleep(0.5)
            await js("$('#changesBtn').click()")

            async def rows():
                for _ in range(40):
                    r = await js("[...document.querySelectorAll('#sheetBody"
                                 " .chrow')].map(r => r.textContent)")
                    if r:
                        return r
                    await asyncio.sleep(0.2)
                return []
            top = await rows()
            tabs = await js("[...document.querySelectorAll('.gtabs button')]"
                            ".map(b => b.textContent + (b.className ? '*' : ''))")
            print("  sin repo abre en:", tabs, top)
            checks += [
                ("sin repo, la hoja abre en Ficheros",
                 tabs == ["Cambios", "Ficheros*"]),
                ("lista la raiz, carpetas primero", len(top) == 6
                 and top[0].startswith("assets")),
            ]
            await js("[...document.querySelectorAll('#sheetBody .chrow')]"
                     ".find(r => r.textContent.startsWith('src')).click()")
            await asyncio.sleep(0.2)
            sub = await rows()
            crumb = await js("$('.fcrumb').textContent")
            print("  en src:", sub, crumb)
            checks.append(("tocar una carpeta entra, con su miga",
                           sub == ["util.py6 B"] and crumb.endswith("/src")))
            await js("$('#sheetBack').click()")
            await asyncio.sleep(0.4)
            up = await rows()
            still = await js("$('#sheet').classList.contains('open')")
            checks.append(("atras sube a la carpeta de arriba sin cerrar",
                           len(up) == 6 and still))

            await js("[...document.querySelectorAll('#sheetBody .chrow')]"
                     ".find(r => r.textContent.startsWith('main.py')).click()")
            view = None
            for _ in range(40):
                view = await js("""(() => { const v = $('.fview');
                  if(!v) return null;
                  const r = [...v.children].map(d =>
                    d.querySelector('i').textContent + '|' +
                    d.querySelector('span').textContent);
                  return {rows: r, h: v.getBoundingClientRect().height,
                          path: $('.gpath').textContent}; })()""")
                if view:
                    break
                await asyncio.sleep(0.2)
            print("  visor:", view)
            checks += [
                ("el fichero se ve con numeros de linea",
                 bool(view) and view["h"] > 0
                 and view["rows"][2] == "3|def run():"),
                ("con su ruta", bool(view) and view["path"] == "main.py"),
            ]
            if os.environ.get("PI_SHOT"):
                await p.shot(os.environ["PI_SHOT"])
            await js("box.innerHTML = ''; $('.fbar button').click()")
            await asyncio.sleep(0.3)
            boxed = await js("[box.textContent,"
                             " $('#sheet').classList.contains('open')]")
            checks.append(("anadir ruta la deja en el compositor y cierra",
                           boxed == ["main.py ", False]))

            await js("openChanges('files'); openDir('assets')")
            await asyncio.sleep(0.6)
            await js("[...document.querySelectorAll('#sheetBody .chrow')]"
                     ".find(r => r.textContent.startsWith('logo')).click()")
            img = None
            for _ in range(40):
                img = await js("(() => { const i = $('.fimg');"
                               " return i && i.complete ? i.naturalWidth"
                               " : null; })()")
                if img:
                    break
                await asyncio.sleep(0.2)
            checks.append(("una imagen se pinta", img == 1))
            codes = await js("""(async () => {
              const q = p => fetch('/api/file?path=' + encodeURIComponent(p)
                + '&token=' + encodeURIComponent(TOKEN)).then(r => r.status);
              return [await q('assets/logo.png'), await q('../x.png'),
                      await q('assets/icon.svg'), await q('main.py')]; })()""")
            print("  /api/file:", codes)
            checks.append(("/api/file: imagen si; ../, SVG y texto no",
                           codes == [200, 404, 404, 404]))
            problems = [x for x in p.problems
                        if "favicon" not in x[1] and "404" not in x[1]]
            checks.append(("sin fallos en consola", not problems))
            if problems:
                print(problems[:4])
    return checks


async def main():
    return unit() + await in_page()


raise SystemExit(report(asyncio.run(main())))
