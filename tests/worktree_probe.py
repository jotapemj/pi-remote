"""Worktrees desde el rail: listar, crear, abrir y quitar.

- Se crean FUERA del repo, en <repo>-worktrees/<rama>; rama existente se
  saca, rama nueva se crea; un nombre invalido o una carpeta que ya existe
  se rechazan.
- Quitar va SIN --force: con cambios sin commitear git se niega y su
  mensaje llega tal cual; el principal y el proyecto abierto no se quitan.
- En la pagina: la hoja lista con rotulos, crear pide la rama en un dialogo
  y la lista se refresca; tocar uno lo abre como proyecto.
Repo temporal de verdad (git init), sin pi real.
"""
import asyncio
import json
import os
import shutil
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


def make_repo(d):
    git(d, "init", "-q", "-b", "main")
    with open(os.path.join(d, "a.txt"), "w") as f:
        f.write("a\n")
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "base")
    git(d, "branch", "ya-existe")


def wt_dir(d):
    return os.path.join(os.path.dirname(d), os.path.basename(d) + "-worktrees")


def unit():
    d = tempfile.mkdtemp(prefix="pi-wt-")
    try:
        make_repo(d)
        p1, e1 = B.wt_add(d, "feat/nueva")
        p2, e2 = B.wt_add(d, "ya-existe")
        _, bad = B.wt_add(d, "no vale..")
        _, dup = B.wt_add(d, "feat/nueva")
        made1 = os.path.isdir(p1)       # antes de quitarlo, mas abajo
        lst = B.wt_list(d)
        rows = [(os.path.basename(w["path"]), w["branch"], w["main"])
                for w in lst["worktrees"]]
        print("  lista:", rows)
        with open(os.path.join(p2, "sucio.txt"), "w") as f:
            f.write("sin commitear\n")
        dirty = B.wt_remove(d, p2)
        clean = B.wt_remove(d, p1)
        main = B.wt_remove(d, d)
        print("  quitar sucio:", dirty)
        after = [w["branch"] for w in B.wt_list(d)["worktrees"]]
        return [
            ("crea con rama nueva, fuera del repo",
             e1 is None and made1
             and os.path.dirname(p1) == wt_dir(d)
             and os.path.basename(p1) == "feat-nueva"),
            ("saca una rama que ya existe", e2 is None and os.path.isdir(p2)),
            ("nombre invalido: rechazado", bad == "invalid branch name"),
            ("carpeta que ya existe: rechazado",
             (dup or "").startswith("folder already exists")),
            ("lista: el principal primero, con sus ramas",
             rows[0][2] is True and rows[0][1] == "main"
             and {r[1] for r in rows} == {"main", "feat/nueva", "ya-existe"}),
            ("con cambios sin commitear git se niega, y se dice por que",
             bool(dirty) and os.path.isdir(p2)
             and ("modified or untracked" in dirty or "--force" in dirty)),
            ("limpio se quita y la carpeta se va",
             clean is None and not os.path.exists(p1)),
            ("el principal no se quita",
             main == "the main worktree cannot be removed"),
            ("la rama se queda tras quitar", after == ["main", "ya-existe"]
             and B.git_run(d, "rev-parse", "--verify", "-q",
                           "refs/heads/feat/nueva")[0] == 0),
            ("fuera de un repo: repo false",
             B.wt_list(tempfile.gettempdir()) == {"repo": False}
             or B.wt_list(tempfile.gettempdir()).get("repo") is False),
        ]
    finally:
        subprocess.run(["git", "-C", d, "worktree", "remove", "--force",
                        os.path.join(wt_dir(d), "ya-existe")],
                       capture_output=True)
        shutil.rmtree(wt_dir(d), ignore_errors=True)
        shutil.rmtree(d, ignore_errors=True)


async def in_page():
    checks = []
    leftover = []
    try:
        await page_flow(checks, leftover)
    finally:
        # con el puente ya parado: el pi falso vivia dentro del worktree
        # abierto y en Windows la carpeta seguia en uso
        # y el proceso tarda un momento en soltarla: reintentar
        for d in leftover:
            for _ in range(25):
                shutil.rmtree(d, ignore_errors=True)
                if not os.path.exists(d):
                    break
                await asyncio.sleep(0.2)
    return checks


async def page_flow(checks, leftover):
    with Bridge(), FakeProject() as proj:
        make_repo(proj.path)
        leftover.append(wt_dir(proj.path))
        if True:
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
                await js("openWorktrees(state.cwd)")

                async def rows(n=1):
                    for _ in range(50):
                        r = await js("[...document.querySelectorAll('#sheetBody"
                                     " .chrow')].map(r => r.textContent)")
                        if len(r) >= n:
                            return r
                        await asyncio.sleep(0.2)
                    return r
                first = await rows()
                print("  hoja:", first)
                checks.append(("lista el principal, rotulado como abierto",
                               len(first) == 1 and first[0].startswith("main")
                               and first[0].endswith("abierto")))

                await js("[...document.querySelectorAll('#sheetBody .pick')]"
                         ".find(b => b.textContent.includes('Worktree nuevo'))"
                         ".click()")
                await asyncio.sleep(0.4)
                dlg = await js("[$('#modal').classList.contains('open'),"
                               " $('#modalTitle').textContent,"
                               " !!$('#modalBody input')]")
                checks.append(("crear pide la rama en un dialogo",
                               dlg == [True, "Worktree nuevo", True]))
                await js("$('#modalBody input').value = 'prueba';"
                         " $('#modalOk').click()")
                two = await rows(2)
                print("  tras crear:", two)
                checks.append(("la lista se refresca con el nuevo",
                               len(two) == 2 and any(r.startswith("prueba")
                                                     for r in two)))
                if os.environ.get("PI_SHOT"):
                    await asyncio.sleep(0.6)
                    await p.shot(os.environ["PI_SHOT"])

                # el abierto no se puede quitar desde aqui (sin puntos)
                dots = await js("[...document.querySelectorAll('#sheetBody"
                                " .chrow')].map(r => !!r.querySelector('.dotsb'))")
                checks.append(("solo los secundarios tienen menu de quitar",
                               dots == [False, True]))

                await js("[...document.querySelectorAll('#sheetBody .chrow')]"
                         ".find(r => r.textContent.startsWith('prueba'))"
                         ".click()")
                want = os.path.join(wt_dir(proj.path), "prueba")
                opened = False
                for _ in range(40):
                    cwd = await js("state.cwd")
                    if cwd and B.same_path(cwd, want):
                        opened = True
                        break
                    await asyncio.sleep(0.2)
                checks.append(("tocarlo lo abre como proyecto", opened))
                problems = [x for x in p.problems if "favicon" not in x[1]]
                checks.append(("sin fallos en consola", not problems))
                if problems:
                    print(problems[:4])


async def main():
    return unit() + await in_page()


raise SystemExit(report(asyncio.run(main())))
