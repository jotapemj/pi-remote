"""Cambios de git: que ha tocado el agente, visto desde el movil.

- git_changes lista lo cambiado (modificado, nuevo, borrado, renombrado,
  binario) con sus lineas +/-; fuera de un repo dice repo:false.
- git_file_diff da el diff de un fichero DE ESA LISTA y nada mas: una ruta
  cualquiera (../, fichero sin cambios) se rechaza.
- En la pagina: el boton de la cabecera lleva el contador, la hoja lista los
  ficheros y al tocar uno pinta su diff coloreado.
Repo temporal de verdad (git init), sin pi real.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile

from harness import ROOT, Bridge, FakeProject, Page, report

sys.path.insert(0, str(ROOT))
import pi_web_bridge as B          # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def git(cwd, *a):
    subprocess.run(["git", "-C", cwd, "-c", "user.name=probe",
                    "-c", "user.email=probe@example.invalid",
                    "-c", "commit.gpgsign=false", *a],
                   check=True, capture_output=True)


def write(cwd, rel, data):
    fp = os.path.join(cwd, *rel.split("/"))
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))


def make_repo(d):
    git(d, "init", "-q", "-b", "main")
    write(d, "app.py", "a = 1\nb = 2\nc = 3\n")
    write(d, "old.txt", "bye\n")
    write(d, "keep.txt", "same\n")
    write(d, "img.bin", b"\x00\x01\x02")
    write(d, "src/deep/mod.py", "x = 1\n")
    write(d, "name1.txt", "renombrame\nuna linea mas\n")
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "base")
    write(d, "app.py", "a = 1\nb = 20\nc = 3\nd = 4\n")      # +2 -1
    os.remove(os.path.join(d, "old.txt"))                    # borrado
    write(d, "img.bin", b"\x00\x09\x09\x09")                 # binario
    write(d, "src/deep/mod.py", "x = 2\n")                   # +1 -1
    write(d, "notes.md", "uno\ndos\ntres\n")                 # nuevo, 3 lineas
    git(d, "mv", "name1.txt", "name2.txt")                   # renombrado


def from_bridge(d):
    ch = B.git_changes(d)
    files = {f["path"]: f for f in ch.get("files", [])}
    print("  ficheros:", {k: (v["kind"], v.get("added"), v.get("removed"))
                          for k, v in files.items()})
    with tempfile.TemporaryDirectory() as plain:
        norepo = B.git_changes(plain)
    app = B.git_file_diff(d, "app.py")
    new = B.git_file_diff(d, "notes.md")
    binf = B.git_file_diff(d, "img.bin")
    ren = B.git_file_diff(d, "name2.txt")
    print("  diff app.py:", app.get("lines"))
    bad = [B.git_file_diff(d, x).get("error")
           for x in ("keep.txt", "../outside.txt", "C:/Windows/win.ini")]
    return [
        ("repo con su rama", ch.get("repo") is True
         and ch.get("branch") == "main"),
        ("modificado con +2 -1", files.get("app.py", {}).get("kind")
         == "modified" and files["app.py"].get("added") == 2
         and files["app.py"].get("removed") == 1),
        ("borrado", files.get("old.txt", {}).get("kind") == "deleted"),
        ("nuevo sin seguir, con sus 3 lineas",
         files.get("notes.md", {}).get("kind") == "new"
         and files["notes.md"].get("added") == 3),
        ("renombrado, con la ruta vieja",
         files.get("name2.txt", {}).get("kind") == "renamed"
         and files["name2.txt"].get("from") == "name1.txt"),
        ("subcarpeta con ruta del repo",
         files.get("src/deep/mod.py", {}).get("kind") == "modified"),
        ("lo que no cambia no sale", "keep.txt" not in files),
        ("fuera de un repo: repo false", norepo == {"repo": False}),
        ("el diff trae los hunks, sin cabeceras de git",
         (app.get("lines") or [""])[0].startswith("@@")
         and "-b = 2" in app["lines"] and "+b = 20" in app["lines"]
         and "+d = 4" in app["lines"]),
        ("fichero nuevo: todo en verde",
         new.get("lines") == ["@@ -0,0 +1,3 @@", "+uno", "+dos", "+tres"]),
        ("binario: se dice, no se pinta", binf.get("binary") is True),
        ("renombrado sin cambios: diff vacio pero sin error",
         "error" not in ren),
        ("solo ficheros de la lista: el resto se rechaza",
         all(bad)),
    ]


async def in_page(d):
    checks = []
    with Bridge(), FakeProject() as proj:
        make_repo(proj.path)
        async with Page() as p:
            js = p.js
            await p.go()
            await asyncio.sleep(0.8)
            await js("setLang('es'); send({type:'open_project', path:%s})"
                     % json.dumps(proj.path))
            badge = None
            for _ in range(60):
                badge = await js("""(() => { const b = $('#changesBtn'),
                  r = b.getBoundingClientRect(), n = $('#chBadge');
                  return {hidden: b.hidden, w: r.width,
                          n: n.textContent,
                          nw: n.getBoundingClientRect().width}; })()""")
                if badge["n"]:
                    break
                await asyncio.sleep(0.2)
            print("  boton:", badge)
            checks += [
                ("con proyecto en un repo, el boton se ve",
                 not badge["hidden"] and badge["w"] > 0),
                ("y su contador cuenta los 6 ficheros",
                 badge["n"] == "6" and badge["nw"] > 0),
            ]

            await js("$('#changesBtn').click()")
            rows = []
            for _ in range(40):
                rows = await js("[...document.querySelectorAll('#sheetBody "
                                ".chrow')].map(r => r.textContent)")
                if rows:
                    break
                await asyncio.sleep(0.2)
            head = await js("[$('#sheetTitle').textContent,"
                            " ($('.gitbr') || {}).textContent]")
            print("  hoja:", head, rows)
            checks += [
                ("la hoja se titula en el idioma activo y da la rama",
                 head == ["Cambios", "main"]),
                ("lista los 6 ficheros", len(rows) == 6),
                ("con marca y lineas", any(r.startswith("M") and "app.py" in r
                                           and "+2" in r and "\u22121" in r
                                           for r in rows)),
            ]
            if os.environ.get("PI_SHOT_LIST"):
                await p.shot(os.environ["PI_SHOT_LIST"])
            await js("[...document.querySelectorAll('#sheetBody .chrow')]"
                     ".find(r => r.textContent.includes('app.py')).click()")
            diff = None
            for _ in range(40):
                diff = await js("""(() => { const d = $('#sheetBody .diff');
                  if(!d) return null; const r = d.getBoundingClientRect();
                  return {add: d.querySelectorAll('.add').length,
                          del: d.querySelectorAll('.del').length,
                          h: r.height,
                          color: getComputedStyle(d.querySelector('.add')).color,
                          title: $('.gpath').textContent}; })()""")
                if diff:
                    break
                await asyncio.sleep(0.2)
            print("  diff:", diff)
            checks += [
                ("al tocar un fichero se pinta su diff",
                 bool(diff) and diff["h"] > 0 and diff["add"] == 2
                 and diff["del"] == 1),
                ("las altas en verde", bool(diff)
                 and diff["color"] != "rgb(0, 0, 0)"),
                ("con la ruta del fichero, tal cual",
                 bool(diff) and diff["title"] == "app.py"),
            ]
            if os.environ.get("PI_SHOT"):
                await p.shot(os.environ["PI_SHOT"])
            # atras vuelve a la lista
            await js("$('#sheetBack').click()")
            await asyncio.sleep(0.6)
            back = await js("document.querySelectorAll('#sheetBody .chrow')"
                            ".length")
            checks.append(("atras vuelve a la lista", back == 6))
            problems = [x for x in p.problems if "favicon" not in x[1]]
            checks.append(("sin fallos en consola", not problems))
            if problems:
                print(problems[:4])
    return checks


async def main():
    with tempfile.TemporaryDirectory() as d:
        make_repo(d)
        out = from_bridge(d)
    return out + await in_page(None)


raise SystemExit(report(asyncio.run(main())))
