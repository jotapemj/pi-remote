"""Piezas comunes de las pruebas. Nada aqui depende de una maquina concreta.

Cada prueba arranca su propio puente contra `fake_pi`, con su propio fichero
de estado, y habla con Chrome por el protocolo de DevTools. No se envia ningun
prompt: el agente de verdad nunca entra en juego.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                       # el proyecto
PORT = int(os.environ.get("PI_TEST_PORT", "8779"))
# el puente ya no ejecuta nada sin token: las pruebas usan uno fijo
TOKEN = "probe-token"
URL = "http://127.0.0.1:%d/?token=%s" % (PORT, TOKEN)
WS_URL = "ws://127.0.0.1:%d/ws?token=%s" % (PORT, TOKEN)

sys.path.insert(0, str(ROOT))

CHROME_CANDIDATES = [
    os.environ.get("CHROME", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_chrome():
    for c in CHROME_CANDIDATES:
        if c and Path(c).exists():
            return c
    found = shutil.which("chrome") or shutil.which("chromium")
    if not found:
        raise SystemExit("no encuentro Chrome. Ponlo en la variable CHROME.")
    return found


CHROME = find_chrome()


def fake_pi_cmd():
    """Un lanzador que Popen sepa ejecutar en cualquier sistema."""
    target = HERE / "fake_pi.py"
    if os.name != "nt":
        os.chmod(target, 0o755)
        return str(target)
    launcher = HERE / "_fake_pi.cmd"
    launcher.write_text('@echo off\r\n"%s" -u "%s" %%*\r\n'
                        % (sys.executable, target), encoding="ascii")
    return str(launcher)


def bridge_env(state=None, extra=None):
    env = dict(os.environ)
    env.update(PI_CMD=fake_pi_cmd(), PI_WEB_PORT=str(PORT),
               PI_WEB_HOST="127.0.0.1", PI_WEB_TOKEN=TOKEN,
               PI_WEB_LOG=str(HERE / "_bridge.log"),
               PI_WEB_STATE=str(state or HERE / "_state.json"))
    if extra:
        env.update(extra)
    return env


class Bridge:
    """El puente corriendo, listo para hablarle."""

    def __init__(self, state=None, extra=None, fresh=True, cleanup=True):
        self.state = Path(state or HERE / "_state.json")
        self.extra = extra
        self.fresh = fresh            # empezar sin recientes
        self.cleanup = cleanup        # borrarlos al terminar

    def __enter__(self):
        if self.fresh and self.state.exists():
            self.state.unlink()
        try:                       # un puente huerfano falsearia la prueba
            urllib.request.urlopen(URL, timeout=1).read()
            raise RuntimeError("el puerto %d ya esta ocupado" % PORT)
        except urllib.error.URLError:
            pass
        self.proc = subprocess.Popen(
            [sys.executable, "pi_web_bridge.py"], cwd=str(ROOT),
            env=bridge_env(self.state, self.extra),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(80):
            try:
                # la raiz no pide token: sirve aunque el puente lo exija
                urllib.request.urlopen(URL, timeout=2).read()
                return self
            except Exception:
                time.sleep(0.25)
        raise RuntimeError("el puente no levanto")

    def __exit__(self, *exc):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        if self.cleanup and self.state.exists():
            self.state.unlink()


def norm(s):
    import re
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


class FakeProject:
    """Una carpeta de proyecto y, opcionalmente, sesiones que pi reconoceria.

    Se crean y se borran aqui: las pruebas no miran las sesiones del usuario.
    """

    def __init__(self, name="probe-project", sessions=0):
        self.name = name
        self.sessions = sessions

    def __enter__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="pi-" + self.name + "-"))
        self.sess_dir = None
        if self.sessions:
            root = Path.home() / ".pi" / "agent" / "sessions"
            root.mkdir(parents=True, exist_ok=True)
            self.sess_dir = root / norm(self.dir)
            self.sess_dir.mkdir(exist_ok=True)
            for i in range(self.sessions):
                f = self.sess_dir / ("2026-01-0%d_probe.jsonl" % (i + 1))
                f.write_text(json.dumps(
                    {"type": "session", "name": "sesion de prueba %d" % i})
                    + "\n", encoding="utf-8")
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.dir, ignore_errors=True)
        if self.sess_dir:
            shutil.rmtree(self.sess_dir, ignore_errors=True)

    @property
    def path(self):
        return str(self.dir)


# ------------------------------------------------------- el navegador

class Page:
    """Chrome sin ventana, hablado por el protocolo de DevTools."""

    def __init__(self, port=9333, width=412, height=880, mobile=True,
                 collect_errors=False):
        self.port, self.w, self.h = port, width, height
        self.mobile, self.collect = mobile, collect_errors
        self.problems = []

    async def __aenter__(self):
        import asyncio
        import websockets
        self.profile = tempfile.mkdtemp(prefix="pi-chrome-")
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new",
             "--remote-debugging-port=%d" % self.port,
             "--user-data-dir=" + self.profile, "--no-first-run",
             "--no-default-browser-check", "--disable-gpu",
             "--window-size=%d,%d" % (self.w, self.h), "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws_url = None
        for _ in range(60):
            try:
                tabs = json.loads(urllib.request.urlopen(
                    "http://127.0.0.1:%d/json" % self.port,
                    timeout=2).read().decode())
                pages = [t for t in tabs if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            time.sleep(0.4)
        if not ws_url:
            raise RuntimeError("chrome no respondio")
        self._ws = await websockets.connect(ws_url, max_size=40 * 1024 * 1024)
        self._n = 0
        await self.cmd("Page.enable")
        await self.cmd("Runtime.enable")
        if self.collect:
            await self.cmd("Log.enable")
            await self.cmd("Network.enable")
        if self.mobile:
            await self.cmd("Emulation.setDeviceMetricsOverride",
                           width=self.w, height=self.h,
                           deviceScaleFactor=2, mobile=True)
        return self

    async def __aexit__(self, *exc):
        try:
            await self._ws.close()
        except Exception:
            pass
        self.proc.terminate()
        shutil.rmtree(self.profile, ignore_errors=True)

    def _note(self, m):
        me, p = m.get("method"), m.get("params", {})
        if me == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            txt = (d.get("exception") or {}).get("description") or d.get("text")
            self.problems.append(("EXCEPCION", (txt or "").split("\n")[0]))
        elif me == "Log.entryAdded" and p.get("entry", {}).get("level") == "error":
            self.problems.append(("ERROR", p["entry"].get("text", "")[:120]))
        elif me == "Network.responseReceived":
            r = p.get("response", {})
            if r.get("status", 200) >= 400:
                self.problems.append(("HTTP %d" % r["status"],
                                      r.get("url", "")[:110]))

    async def cmd(self, method, **params):
        import asyncio
        self._n += 1
        await self._ws.send(json.dumps({"id": self._n, "method": method,
                                        "params": params}))
        while True:
            m = json.loads(await asyncio.wait_for(self._ws.recv(), 30))
            if m.get("id") == self._n:
                return m.get("result", {})
            self._note(m)

    async def js(self, expr):
        r = await self.cmd("Runtime.evaluate", expression=expr,
                           returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            return ["ERR", r["exceptionDetails"].get("text")]
        return r.get("result", {}).get("value")

    async def go(self, url=URL, settle=2.2):
        import asyncio
        await self.cmd("Page.navigate", url=url)
        await asyncio.sleep(settle)

    async def drain(self, seconds=1.0):
        """Recoge errores del navegador durante un rato."""
        import asyncio
        end = time.time() + seconds
        while time.time() < end:
            try:
                self._note(json.loads(
                    await asyncio.wait_for(self._ws.recv(), 0.4)))
            except asyncio.TimeoutError:
                pass

    async def shot(self, path):
        import base64
        r = await self.cmd("Page.captureScreenshot", format="png")
        Path(path).write_bytes(base64.b64decode(r["data"]))


def report(checks):
    for label, good in checks:
        print("  " + ("ok    " if good else "FALLA ") + label)
    ok = all(g for _, g in checks)
    print("\n" + ("TODO OK" if ok else "FALLA"))
    return 0 if ok else 1
