"""Smoke contra el pi REAL (no fake_pi): lo que la suite no ve al cambiar de
version de pi. Usa el modelo de verdad, tarda minutos; NO va en run.py.

    python tests/realpi_smoke.py [--out base.json] [--skip-model]

Proyecto temporal propio; las sesiones que pi graba para el se borran al
final. Las sesiones reales solo se leen, y en copia (pi migra al abrir).
Variables: PI_CMD (como el puente), SMOKE_TIMEOUT (s por turno, 300),
SMOKE_MODEL=proveedor/id (si el modelo por defecto no esta servido).
"""
import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
AGENT = Path.home() / ".pi" / "agent"
ASK_EXT = HERE / "extensions" / "ask_user.ts"
ASK_MARK = "pi-remote:ask_user"
PI_CMD = os.environ.get("PI_CMD") or shutil.which("pi") or "pi"
TURN = float(os.environ.get("SMOKE_TIMEOUT") or 300)
NEEDS_ANSWER = ("select", "confirm", "input", "editor")


class Pi:
    def __init__(self, cwd):
        args = [PI_CMD, "--mode", "rpc"]
        if ASK_EXT.is_file():
            args += ["-e", str(ASK_EXT)]
        self.t0 = time.monotonic()
        self.p = subprocess.Popen(
            args, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
            bufsize=1)
        self.q = queue.Queue()
        self.stderr = []
        self.n = 0
        threading.Thread(target=self._out, daemon=True).start()
        threading.Thread(target=self._err, daemon=True).start()

    def _out(self):
        for line in self.p.stdout:
            line = line.rstrip("\r\n")
            if not line:
                continue
            try:
                self.q.put(json.loads(line))
            except ValueError:
                self.q.put({"type": "_raw", "line": line[:300]})
        self.q.put({"type": "_eof"})

    def _err(self):
        for line in self.p.stderr:
            self.stderr.append(line.rstrip("\r\n"))

    def send(self, cmd):
        self.p.stdin.write(json.dumps(cmd) + "\n")
        self.p.stdin.flush()

    def call(self, typ, timeout=60, **kw):
        """Comando con id; devuelve su response. Lo demas, a `seen`."""
        self.n += 1
        rid = "s%d" % self.n
        self.send(dict(kw, type=typ, id=rid))
        return self.until(lambda m: m.get("type") == "response"
                          and m.get("id") == rid, timeout)

    def until(self, pred, timeout, on_ui=None, seen=None):
        """Consume eventos hasta pred. Los dialogos se pasan a on_ui; sin
        on_ui se cancelan (y quedan en `seen` para el informe)."""
        end = time.monotonic() + timeout
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return None
            try:
                m = self.q.get(timeout=left)
            except queue.Empty:
                return None
            if seen is not None:
                seen.append(m)
            if m.get("type") == "_eof":
                return None
            if (m.get("type") == "extension_ui_request"
                    and m.get("method") in NEEDS_ANSWER):
                ans = on_ui(m) if on_ui else None
                if ans is None:
                    ans = {"cancelled": True}
                self.send(dict(ans, type="extension_ui_response", id=m["id"]))
            if pred(m):
                return m

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=15)
        except Exception:
            self.p.kill()


def settled(m):
    return m.get("type") == "agent_settled"


def last_text(pi):
    r = pi.call("get_last_assistant_text")
    return ((r or {}).get("data") or {}).get("text") or ""


def ui_brief(m):
    return {k: m.get(k) for k in ("method", "title", "options", "message")
            if m.get(k) is not None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="JSON con el informe (para comparar)")
    ap.add_argument("--skip-model", action="store_true",
                    help="solo lo que no gasta modelo")
    a = ap.parse_args()

    ver = subprocess.run([PI_CMD, "--version"], capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    rep = {"pi": (ver.stdout or ver.stderr).strip(), "cmd": PI_CMD,
           "checks": [], "info": {}}

    def check(name, ok, **info):
        rep["checks"].append({"name": name, "ok": bool(ok), **info})
        print("  %s  %s%s" % ("ok  " if ok else "FAIL", name,
                              ("  " + json.dumps(info, ensure_ascii=False)[:300])
                              if info else ""))

    tmp = Path(tempfile.mkdtemp(prefix="pismoke-"))
    (tmp / "basura").mkdir()
    (tmp / "basura" / "x.txt").write_text("no borrar")
    session_files = set()
    pi = Pi(tmp)
    print("pi: %s  proyecto: %s" % (rep["pi"], tmp))
    try:
        # ---- arranque y estado ----
        r = pi.call("get_state", timeout=120)
        rep["info"]["startup_s"] = round(time.monotonic() - pi.t0, 2)
        st = (r or {}).get("data") or {}
        if st.get("sessionFile"):
            session_files.add(st["sessionFile"])
        check("arranca y contesta get_state", r and r.get("success"),
              secs=rep["info"]["startup_s"])
        model = st.get("model") or {}
        check("modelo por defecto cargado (models.json se lee)",
              model.get("id"), model="%s/%s" % (model.get("provider"),
                                                 model.get("id")))
        r = pi.call("get_available_models")
        models = ((r or {}).get("data") or {}).get("models") or []
        check("lista de modelos", len(models) > 0, n=len(models))

        r = pi.call("get_commands")
        cmds = ((r or {}).get("data") or {}).get("commands") or []
        names = sorted(c.get("name", "") for c in cmds)
        rep["info"]["commands"] = names
        check("get_commands contesta", r and r.get("success"), n=len(names))

        # errores de extensiones al cargar: eventos y stderr
        seen = []
        pi.until(lambda m: False, 2, seen=seen)
        ext_err = [m for m in seen if m.get("type") == "extension_error"]
        bad = [l for l in pi.stderr if any(w in l.lower() for w in
               ("error", "failed", "cannot find", "incompatible"))]
        rep["info"]["stderr"] = pi.stderr[-40:]
        check("sin extension_error al cargar", not ext_err,
              errs=[m.get("error") or m for m in ext_err][:5])
        check("stderr sin errores", not bad, lines=bad[:8])

        # ---- /bash del usuario: salida limpia ----
        r = pi.call("bash", timeout=60, command="echo hola")
        out = ((r or {}).get("data") or {}).get("output") or ""
        check("bash RPC devuelve la salida", "hola" in out, out=out[:80])
        check("bash RPC sin codigos de color", "\x1b" not in out)

        # ---- sesion vieja (copia): se lee entera ----
        olds = sorted((AGENT / "sessions").glob("*/*.jsonl"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        olds = [p for p in olds if p.stat().st_size < 3_000_000][:1]
        if olds:
            cp = tmp / ("old-" + olds[0].name)
            shutil.copy2(olds[0], cp)
            r = pi.call("switch_session", timeout=60, sessionPath=str(cp))
            ok = r and r.get("success") and not (r.get("data") or {}).get(
                "cancelled")
            r = pi.call("get_messages", timeout=60)
            msgs = ((r or {}).get("data") or {}).get("messages") or []
            check("abre una sesion grabada y trae sus mensajes",
                  ok and len(msgs) > 0, n=len(msgs))
            r = pi.call("new_session", timeout=60)
            r = pi.call("get_state")
            sf = ((r or {}).get("data") or {}).get("sessionFile")
            if sf:
                session_files.add(sf)
            check("new_session vuelve a una sesion vacia", sf and
                  not same(sf, cp))

        if a.skip_model:
            return rep

        want = os.environ.get("SMOKE_MODEL")
        if want:
            prov, _, mid = want.partition("/")
            r = pi.call("set_model", provider=prov, modelId=mid)
            check("SMOKE_MODEL aplicado", r and r.get("success"), model=want)
        pi.call("set_thinking_level", level="off")

        # ---- turno simple con el modelo ----
        seen = []
        pi.call("prompt", message="Responde solo con la palabra: LISTO")
        m = pi.until(settled, TURN, seen=seen)
        check("turno simple llega a agent_settled", m)
        txt = last_text(pi)
        check("el modelo contesta", "LISTO" in txt.upper(), text=txt[:80])
        check("sin dialogos inesperados", not [x for x in seen if x.get(
            "type") == "extension_ui_request" and x.get("method")
            in NEEDS_ANSWER], seen=[ui_brief(x) for x in seen if x.get(
                "type") == "extension_ui_request"][:3])

        # ---- permission gate: rm pide permiso; se deniega ----
        asked = []

        def deny(m):
            asked.append(ui_brief(m))
            if m.get("method") == "confirm":
                return {"confirmed": False}
            if m.get("method") == "select":
                for o in m.get("options") or []:
                    if any(w in str(o).lower() for w in ("deny", "deneg",
                                                         "reject", "no")):
                        return {"value": o}
            return None                    # cancelar
        pi.call("prompt", message=(
            "Usa la herramienta bash para ejecutar exactamente este comando y "
            "nada mas: rm -rf basura"))
        m = pi.until(settled, TURN, on_ui=deny)
        check("rm pasa por el dialogo de permisos", asked, asked=asked[:2])
        check("denegado, el directorio sigue ahi",
              (tmp / "basura" / "x.txt").is_file())

        # ---- ask_user (extension de pi-remote) ----
        got = []

        def answer(m):
            got.append(ui_brief(m))
            if m.get("method") == "editor" and m.get("title") == ASK_MARK:
                return {"value": json.dumps(
                    {"answers": [{"selected": ["azul"]}]})}
            return None
        pi.call("prompt", message=(
            "Usa la herramienta ask_user para preguntarme mi color favorito, "
            "con las opciones rojo y azul. Luego responde solo con el color "
            "que elegi."))
        m = pi.until(settled, TURN, on_ui=answer)
        txt = last_text(pi)
        check("ask_user abre su dialogo editor",
              any(g.get("title") == ASK_MARK for g in got), got=got[:2])
        check("la respuesta vuelve al modelo", "azul" in txt.lower(),
              text=txt[:80])

        # ---- abort a mitad de respuesta ----
        seen = []
        pi.call("prompt", message=(
            "Escribe una lista numerada del 1 al 150; cada numero con una "
            "frase distinta."))
        first = pi.until(lambda m: m.get("type") == "message_update", TURN,
                         seen=seen)
        t = time.monotonic()
        pi.send({"type": "abort"})        # sin call(): se tragaria el settled
        m = pi.until(settled, 60, seen=seen)
        rep["info"]["abort_settled"] = m
        check("abort asienta el turno rapido", first and m,
              secs=round(time.monotonic() - t, 1),
              aborted=(m or {}).get("aborted"))
        r = pi.call("prompt", message="Responde solo: SIGO")
        m = pi.until(settled, TURN)
        check("tras abort la sesion sigue viva",
              m and "SIGO" in last_text(pi).upper())

        r = pi.call("get_state")
        sf = ((r or {}).get("data") or {}).get("sessionFile")
        if sf:
            session_files.add(sf)
        return rep
    finally:
        pi.close()
        rep["info"]["stderr_tail"] = pi.stderr[-20:]
        # solo las sesiones de ESTE proyecto temporal
        for f in session_files:
            d = Path(f).parent
            if "pismoke" in d.name.lower() and d.parent == AGENT / "sessions":
                shutil.rmtree(d, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)
        fails = [c["name"] for c in rep["checks"] if not c["ok"]]
        print("\n%d/%d ok" % (len(rep["checks"]) - len(fails),
                              len(rep["checks"])))
        if a.out:
            Path(a.out).write_text(json.dumps(rep, indent=1,
                                              ensure_ascii=False, default=str),
                                   encoding="utf-8")


def same(a, b):
    return os.path.normcase(os.path.abspath(str(a))) == \
        os.path.normcase(os.path.abspath(str(b)))


if __name__ == "__main__":
    rep = main()
    sys.exit(0 if all(c["ok"] for c in rep["checks"]) else 1)
