"""Las listas de conversaciones se ordenan por el ultimo MENSAJE, no por el
mtime. Abrir una sesion hace que pi anote en ella el model_change /
thinking_level_change con que el puente impone el modelo por defecto: el
mtime subia y la sesion saltaba arriba solo por abrirla. Y al terminar un
turno el rail pide la lista de nuevo: una sesion nueva no existe en disco
hasta la primera respuesta, asi que al nacer (o al llegar su nombre) aun no
salia, y no volvia a pedirse.
"""
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

from harness import Bridge, Page, report


def line(**e):
    return json.dumps(e) + "\n"


def backend():
    import pi_web_bridge as B
    checks = []
    d = Path(tempfile.mkdtemp())
    old = d / "old.jsonl"      # hablada hace mas, pero abierta ahora
    new = d / "new.jsonl"      # hablada despues, sin abrir
    old.write_text(
        line(type="session", id="a", timestamp="2026-09-20T10:00:00.000Z")
        + line(type="message", id="m1", timestamp="2026-09-20T10:05:00.000Z",
               message={"role": "user", "content": "hola"})
        # lo que anota pi al abrirla: no es hablar
        + line(type="model_change", id="c1", timestamp="2026-09-27T09:00:00.000Z",
               provider="p", modelId="m")
        + line(type="thinking_level_change", id="c2",
               timestamp="2026-09-27T09:00:00.000Z", thinkingLevel="xhigh"),
        encoding="utf-8")
    new.write_text(
        line(type="session", id="b", timestamp="2026-09-22T10:00:00.000Z")
        + line(type="message", id="m2", timestamp="2026-09-22T10:05:00.000Z",
               message={"role": "user", "content": "adios"}), encoding="utf-8")
    now = time.time()
    os.utime(new, (now - 3600, now - 3600))
    os.utime(old, (now, now))          # el mtime dice que old es la nueva
    # una linea enorme al final (salida con imagen): la cola se lee a trozos
    big = d / "big.jsonl"
    big.write_text(
        line(type="message", id="m3", timestamp="2026-09-21T10:00:00.000Z",
             message={"role": "user", "content": "x"})
        + line(type="custom", id="z", data="y" * 600_000), encoding="utf-8")
    empty = d / "empty.jsonl"
    empty.write_text(line(type="session", id="e",
                          timestamp="2026-09-01T00:00:00.000Z"), encoding="utf-8")
    ts = B._ts_seconds
    real = B.session_dir
    B.session_dir = lambda cwd: d
    try:
        order = [Path(x["path"]).stem for x in B.list_sessions("X")]
        found = [Path(x["path"]).stem for x in B.search_sessions(["X"], "")]
    finally:
        B.session_dir = real
    print("  lista=%s busqueda=%s" % (order, found))
    checks += [
        ("la hora es la del ultimo mensaje, no la del model_change",
         B.last_activity(old) == int(ts("2026-09-20T10:05:00.000Z"))),
        ("con una linea enorme detras tambien la encuentra",
         B.last_activity(big) == int(ts("2026-09-21T10:00:00.000Z"))),
        ("sin mensajes cae al mtime",
         B.last_activity(empty) == int(empty.stat().st_mtime)),
        ("la carpeta ordena por conversacion: abrir no sube",
         order.index("new") < order.index("big") < order.index("old")),
        ("recientes y busqueda igual", found.index("new") < found.index("old")),
    ]
    return checks


async def ui():
    checks = []
    with Bridge():
        async with Page() as p:
            await p.go()
            await asyncio.sleep(0.8)
            r = await p.js("""(async () => {
              const urls = [];
              const f0 = window.fetch;
              window.fetch = (u, o) => { urls.push(String(u));
                return Promise.resolve(new Response('{"sessions":[],"results":[]}')); };
              const cwd = 'C:/proj';
              sessCache[cwd] = [{path:'C:/proj/a.jsonl', label:'a', mtime:1}];
              openProj = cwd;
              const base = Object.assign({}, state, {cwd,
                recent:[{path:cwd, name:'proj'}]});
              applyState({state: Object.assign({}, base, {running:true})});
              await new Promise(r => setTimeout(r, 50));
              const during = urls.length;
              const shown = !!groupOf(cwd).querySelector('.sess:not(.new)');
              urls.length = 0;
              applyState({state: Object.assign({}, base, {running:false})});
              const kept = !!groupOf(cwd).querySelector('.sess:not(.new)');
              await new Promise(r => setTimeout(r, 100));
              window.fetch = f0;
              return {during, shown, kept, urls};
            })()""")
            print("  ", r)
            checks += [
                ("al terminar el turno se pide la carpeta abierta",
                 any("/api/sessions" in u and "proj" in u for u in r["urls"])),
                ("y los recientes",
                 any("/api/search" in u for u in r["urls"])),
                ("sin parpadeo: la lista vieja sigue hasta la nueva",
                 r["shown"] and r["kept"]),
            ]
    return checks


async def main():
    return backend() + await ui()

raise SystemExit(report(asyncio.run(main())))
