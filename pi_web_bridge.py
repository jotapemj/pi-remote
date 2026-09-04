#!/usr/bin/env python3
"""
Web bridge for the pi coding agent. Sibling of pi_telegram_bridge.py.

Wraps `pi --mode rpc` and exposes it over WebSocket, so you can drive a
session from a phone browser across Tailscale.

    pip install fastapi "uvicorn[standard]"
    cd C:\\path\\to\\project
    python pi_web_bridge.py

Then open http://<tailscale-name>:8770

Env:
    PI_CMD        path to pi           (default: auto-detected)
    PI_RESUME     new | continue       (default: new)
    PI_SESSION    session name         (default: web)
    PI_WEB_HOST   bind address         (default: 0.0.0.0)
    PI_WEB_PORT   port                 (default: 8770)
    PI_WEB_TOKEN  shared secret        (default: one is generated;
                                       "off" drops to read only)
"""

import asyncio
import json
import os
import re
import difflib
import hmac
import secrets
import socket
import shutil
import subprocess
import sys
import threading
import time
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response

PI_CMD = os.environ.get("PI_CMD") or shutil.which("pi") or "pi"
RESUME = os.environ.get("PI_RESUME", "new")
SESSION_NAME = os.environ.get("PI_SESSION", "web")
HOST = os.environ.get("PI_WEB_HOST", "0.0.0.0")
PORT = int(os.environ.get("PI_WEB_PORT", "8770"))
# Un puente sin secreto deja ejecutar a cualquiera que alcance el puerto,
# asi que no se permite esa combinacion: o hay token, o no se ejecuta nada.
_given = os.environ.get("PI_WEB_TOKEN", "").strip()
READ_ONLY = _given.lower() in ("off", "no", "none")
TOKEN = "" if READ_ONLY else (_given or secrets.token_urlsafe(18))
TOKEN_MADE = bool(not READ_ONLY and not _given)

# Lo unico que se atiende cuando no hay token: mirar, nunca tocar.
READ_CMDS = {"get_state", "get_messages", "get_session_stats",
             "get_available_models", "get_available_thinking_levels",
             "get_commands"}
ALLOW_ORIGINS = [o.strip() for o in
                 os.environ.get("PI_WEB_ORIGINS", "").split(",")
                 if o.strip()]

HERE = Path(__file__).resolve().parent
INDEX = HERE / "static" / "index.html"
FONTS = HERE / "static" / "fonts"
LOG_FILE = os.environ.get("PI_WEB_LOG", "")
# el harness apunta esto a otro sitio: sus pruebas no deben
# tocar los proyectos que el usuario tiene guardados
STATE_FILE = Path(os.environ.get("PI_WEB_STATE") or HERE / "state.json")

def _version():
    """Fuente unica: version.txt en la raiz."""
    try:
        return (HERE / "version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"


VERSION = _version()
START_CWD = os.environ.get("PI_WEB_CWD", "")

LOG_MAX = 2 * 1024 * 1024        # corriendo meses, el log llena el disco

# pythonw.exe no da consola: sys.stdout es None y todo print() revienta.
if LOG_FILE or sys.stdout is None:
    _log = Path(LOG_FILE or HERE / "bridge.log")
    try:                         # una vuelta de rotacion basta para depurar
        if _log.is_file() and _log.stat().st_size > LOG_MAX:
            _log.replace(_log.with_name(_log.name + ".1"))
    except OSError:
        pass
    sys.stdout = sys.stderr = open(_log, "a", encoding="utf-8",
                                   errors="replace", buffering=1)

LOG_CAP = 400            # transcript items kept for reconnecting clients
RECENT_CAP = 12          # projects remembered for the sidebar
HISTORY_CAP = 150        # messages replayed when a session opens
DIFF_CAP = 400           # diff lines kept per edit


# Commands a browser may forward straight to pi. Everything else is refused.
PASSTHROUGH = {
    "prompt", "steer", "follow_up", "clear_queue", "new_session",
    "get_state", "get_messages", "set_model", "cycle_model",
    "get_available_models", "set_thinking_level", "get_available_thinking_levels",
    "compact", "set_auto_compaction", "set_auto_retry", "abort_retry",
    "bash", "abort_bash", "get_session_stats", "export_html", "switch_session",
    "fork", "clone", "get_fork_messages", "get_last_assistant_text",
    "set_session_name", "get_commands", "set_steering_mode",
    "set_follow_up_mode",
}


# ------------------------------------------------------------------ access

def good_token(given):
    """Constant time, so the token cannot be guessed a byte at a time."""
    if not TOKEN:                     # solo lectura: no hay nada que abrir
        return True
    return hmac.compare_digest(given or "", TOKEN)


def same_origin(request):
    """Websockets ignore the same-origin policy: any page you visit could
    open one against this port and drive the agent. Browsers always send
    Origin, so a missing one is a non-browser client and is let through."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    if origin in ALLOW_ORIGINS:
        return True
    try:
        return urlparse(origin).netloc == request.headers.get("host", "")
    except ValueError:
        return False


CSP = ("default-src 'none'; script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline'; font-src 'self'; "
       "img-src 'self' data:; connect-src 'self'; "
       "manifest-src 'self'; worker-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

SAFE_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


# ------------------------------------------------------------ session files

def sessions_root():
    return Path.home() / ".pi" / "agent" / "sessions"


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


def session_dir(cwd):
    """Find pi's folder for a project dir without guessing its slug."""
    root = sessions_root()
    if not root.is_dir():
        return root
    dirs = [d for d in root.iterdir() if d.is_dir()]
    target = _norm(cwd)
    for d in dirs:
        if _norm(d.name) == target:
            return d
    tail = _norm(Path(cwd).name)
    matches = [d for d in dirs if tail and tail in _norm(d.name)]
    if len(matches) == 1:
        return matches[0]
    if matches:
        return max(matches, key=lambda d: d.stat().st_mtime)
    return root


def session_label(path):
    """Nombre para el arbol, con esta prioridad:

    1. la ultima entrada `session_info`: pi anota CADA rebautizado al final
       del fichero y el propio pi lee el nombre escaneando hacia atras.
       Una ventana fija desde el final no basta: en una sesion activa el
       rename puede quedar a megas del borde.
    2. el nombre de creacion (cabecera) o el primer mensaje de usuario.

    Un solo pase; solo se parsea lo que el prefiltro de cadena deja pasar.
    """
    info = None
    head = None
    try:
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i < 40 and head is None:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        e = None
                    if e:
                        t = e.get("type")
                        if t == "session" and e.get("name"):
                            head = e["name"]
                        elif t == "message":
                            msg = e.get("message") or {}
                            if msg.get("role") == "user":
                                c = msg.get("content")
                                if isinstance(c, str):
                                    head = c[:60]
                                else:
                                    for blk in c or []:
                                        if blk.get("type") == "text":
                                            head = blk["text"][:60]
                                            break
                # prefiltro barato antes de parsear ficheros de varios MB;
                # el tipo se confirma despues, ya parseado
                if "session_info" in line:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if e.get("type") == "session_info":
                        n = (e.get("name") or "").strip()
                        if n:
                            info = n        # la ultima gana
    except OSError:
        pass
    return info or head or path.stem[:60]


def trash_session(path, active):
    """pi has no delete over rpc, so the file is moved aside.

    Not deleted: a session is your own work and a stray tap on a phone
    should not destroy it. Returns an error key, or "" when it worked.
    """
    if not path:
        return "bad_path"
    try:
        target = Path(path).resolve()
        root = sessions_root().resolve()
    except OSError:
        return "bad_path"
    if root not in target.parents:
        return "outside"             # only inside pi's own sessions folder
    if target.suffix != ".jsonl" or not target.is_file():
        return "missing"
    if active:
        try:
            if target == Path(active).resolve():
                return "in_use"
        except OSError:
            pass
    bin_dir = target.parent / "_trash"
    try:
        bin_dir.mkdir(exist_ok=True)
        dest = bin_dir / target.name
        i = 1
        while dest.exists():
            dest = bin_dir / f"{target.stem}.{i}{target.suffix}"
            i += 1
        target.rename(dest)
    except OSError:
        return "failed"
    return ""


def list_sessions(cwd, limit=20):
    d = session_dir(cwd)
    if not d.is_dir():
        return []
    files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    return [{"path": str(f), "label": session_label(f),
             "mtime": int(f.stat().st_mtime)} for f in files[:limit]]


def edit_diff(args):
    """Las lineas que cambia una llamada a `edit`.

    Se calcula de los propios argumentos, que traen `oldText` y `newText`.
    El resultado de pi tambien lleva un diff, pero su forma no esta
    documentada y las extensiones la cambian; esto no depende de eso.
    """
    lines, added, removed = [], 0, 0
    for e in args.get("edits") or []:
        old = (e.get("oldText") or "").splitlines()
        new = (e.get("newText") or "").splitlines()
        for ln in difflib.unified_diff(old, new, lineterm="", n=2):
            if ln.startswith(("---", "+++")):
                continue
            if ln.startswith("+"):
                added += 1
            elif ln.startswith("-"):
                removed += 1
            if len(lines) < DIFF_CAP:
                lines.append(ln)
    if not (added or removed):
        return None
    return {"lines": lines, "added": added, "removed": removed}


def pct(tokens, window):
    """El porcentaje que pi no siempre manda, pero que se deduce."""
    try:
        if tokens is None or not window:
            return None
        return round(100.0 * tokens / window, 2)
    except (TypeError, ZeroDivisionError):
        return None


def same_path(a, b):
    """Dos rutas que apuntan al mismo sitio, con las manias de Windows."""
    if not a or not b:
        return False
    try:
        return os.path.normcase(os.path.realpath(a)) == \
               os.path.normcase(os.path.realpath(b))
    except OSError:
        return False


def grab_usage(ev):
    """El usage puede venir suelto o dentro del mensaje."""
    u = ev.get("usage")
    if not u:
        u = (ev.get("message") or {}).get("usage")
    return u if isinstance(u, dict) and u else None


def tool_gist(args):
    """Lo que de verdad va a ejecutarse, sacado de los argumentos."""
    for key in ("command", "code", "path", "filePath", "file_path",
                "pattern", "url", "query"):
        v = (args or {}).get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    if args:
        return json.dumps(args, ensure_ascii=False)
    return ""


def text_of(content):
    """A message body is either a string or a list of typed blocks."""
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or []
                      if b.get("type") == "text")


IMG_MIME = re.compile(r"^image/(png|jpe?g|webp|gif)$", re.I)
IMG_CAP = 1_500_000              # base64 chars; lo mas gordo no se guarda


def images_of(content):
    """Bloques de imagen (base64) de un content de mensaje o tool result.

    Una herramienta como `read` sobre una imagen devuelve el fichero como
    ImageContent junto al texto "Read image file". pi ya la redimensiona;
    aun asi se descarta lo que pase del tope, para no engordar el snapshot.
    """
    out = []
    for b in content or []:
        if not isinstance(b, dict):
            continue
        data = b.get("data")
        if (b.get("type") == "image" and data
                and IMG_MIME.match(b.get("mimeType") or "")
                and len(data) <= IMG_CAP):
            out.append({"type": "image", "data": data,
                        "mimeType": b["mimeType"]})
    return out


# ---------------------------------------------------------------- browsing

def browse_root():
    """Where the folder picker starts: the Users folder on Windows."""
    return Path.home().parent if os.name == "nt" else Path.home()


def looks_like_project(d):
    """A hint on the card, so you recognise the folder you want."""
    for mark in (".git", "build.gradle", "build.gradle.kts", "settings.gradle",
                 "settings.gradle.kts", "package.json", "pyproject.toml",
                 "CMakeLists.txt", "platformio.ini", "Cargo.toml"):
        if (d / mark).exists():
            return mark
    return ""


def list_dirs(path):
    """Subfolders of path, skipping what we may not read."""
    out = []
    try:
        entries = sorted(path.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return out
    for d in entries:
        try:
            if not d.is_dir() or d.name.startswith((".", "$")):
                continue
            d.iterdir()                      # unreadable folders stay hidden
        except OSError:
            continue
        out.append({"name": d.name, "path": str(d),
                    "mark": looks_like_project(d)})
    return out


def read_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def read_last():
    return read_state().get("cwd") or ""


def read_recent():
    """Folders that are still there, newest first."""
    out = []
    for c in read_state().get("recent") or []:
        if isinstance(c, str) and Path(c).is_dir():
            out.append({"path": c, "name": Path(c).name})
    return out


def write_state(cwd, paths):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump({"cwd": cwd, "recent": paths}, fh, indent=1)
    except OSError as exc:
        print("state:", exc, file=sys.stderr)
    return [{"path": p, "name": Path(p).name} for p in paths]


def remember(cwd):
    """Put cwd at the head of the recents and write them back."""
    paths = [c["path"] for c in read_recent()
             if c["path"].lower() != cwd.lower()]
    paths.insert(0, cwd)
    return write_state(cwd, paths[:RECENT_CAP])


def forget(cwd, current):
    """Drop one folder from the list. The open project stays open."""
    paths = [c["path"] for c in read_recent()
             if c["path"].lower() != cwd.lower()]
    return write_state(current, paths)


# ------------------------------------------------------------------ bridge

class Bridge:
    """Owns the pi subprocess and fans its events out to browsers."""

    def __init__(self, loop):
        self.loop = loop
        self.clients = set()
        self.lock = threading.Lock()

        self.log = deque(maxlen=LOG_CAP)     # transcript for reconnects
        self.seq = 0
        self.state = {
            "running": False, "startedAt": 0, "tool": None,
            "sessionName": None, "model": None, "thinking": None,
            "context": None, "queue": {"steering": [], "followUp": []},
            "alive": True, "cwd": "", "waiting": False, "recent": [],
            "sessionFile": None,
            # como servicio nadie lee la consola: el aviso va a la pantalla
            "readOnly": READ_ONLY, "version": VERSION,
        }
        self.pending = OrderedDict()         # dialog id -> item id
        self.compacting = None               # la nota "compactando" en curso
        self.prefill_t0 = None               # cuando arranco el prefill actual
        self.gen_first = None                # instante del primer token
        self.gen_prompt_ms = None            # prefill de la respuesta actual
        self.cur_usage = {}                  # usage acumulado de la respuesta
        self.assistant_open = False          # hay una respuesta en curso
        self.produced = False                # el turno ya genero algo
        self.cur = None                      # assistant item being streamed

        self.proc = None                     # no project, no agent
        self.cwd = ""
        self.gen = 0                         # so a replaced reader stays quiet
        self.stopped = False

        self.state["recent"] = read_recent()
        first = START_CWD or read_last()
        if first and Path(first).is_dir():
            self.open_project(first)

    # ---- the agent, per project

    def open_project(self, cwd, session=None):
        """Point the bridge at a folder: stop the old pi, start one there.

        With `session`, load that session file instead of starting a new one.
        """
        cwd = str(Path(cwd).resolve())
        if not Path(cwd).is_dir():
            self.note("error", "not_folder", f"not a folder: {cwd}",
                      path=cwd)
            return

        # Volver a lo que ya esta abierto es volver, no reiniciar. Y si hay
        # un dialogo esperando respuesta, reiniciar mata al pi que espera:
        # la tarjeta se va, pero nadie puede ya contestarla.
        if (self.proc and same_path(cwd, self.cwd)
                and (not session
                     or same_path(session, self.state.get("sessionFile")))):
            self.emit(self.snapshot())
            return

        dropped = len(self.pending)   # pi se va, y con el quien esperaba
        self.stop_pi()
        self.log.clear()
        self.cur = None
        self.pending.clear()
        self.emit({"type": "cleared"})
        if dropped:
            self.note("warn", "dropped_ask",
                      "%d approval request was dropped: that pi is gone"
                      % dropped, n=dropped)

        args = [PI_CMD, "--mode", "rpc"]
        if session:
            pass                      # switch_session below picks the file
        elif RESUME == "continue":
            args.append("-c")
        else:
            args += ["--name", SESSION_NAME]
        try:
            self.proc = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=cwd,
                encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            self.proc = None
            self.note("error", "start_failed",
                      f"could not start pi: {exc}", err=str(exc))
            return

        self.cwd = cwd
        self.gen += 1
        self.state.update(alive=True, running=False, tool=None, cwd=cwd,
                          context=None, sessionName=None, waiting=False,
                          recent=remember(cwd))
        threading.Thread(target=self.reader, args=(self.proc, self.gen),
                         daemon=True).start()
        self.note("info", "project", f"project: {cwd}", path=cwd)
        self.send_pi({"type": "get_state"})
        if session:
            # switch_session clears and reloads on its own: no double fetch
            self.send_pi({"type": "switch_session", "sessionPath": session})
        else:
            self.send_pi({"type": "get_messages"})
        self.push_state()

    def stop_pi(self):
        """Close stdin: pi drains and exits 0. terminate() gives EPIPE."""
        proc, self.proc = self.proc, None
        if not proc:
            return
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()

    # ---- plumbing

    def send_pi(self, cmd):
        if not self.proc:
            self.note("warn", "no_project",
                      "no project open. pick a folder first.")
            return
        with self.lock:
            try:
                self.proc.stdin.write(json.dumps(cmd) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError) as exc:
                self.note("error", "pi_stdin",
                          f"pi is not accepting input: {exc}", err=str(exc))

    def poll_stats(self, times=8, every=1.6):
        """Una rafaga corta de get_session_stats, para ver subir la barra."""
        gen = self.gen

        def run():
            for _ in range(times):
                time.sleep(every)
                if gen != self.gen or not self.proc:
                    return
                self.send_pi({"type": "get_session_stats"})

        threading.Thread(target=run, daemon=True).start()

    def build_stats(self, usage):
        """Conteos que da pi, y velocidades que mide el puente."""
        now = time.time()
        first = self.gen_first or now
        prompt_ms = self.gen_prompt_ms or 0
        gen_ms = int(max(0.0, (now - first)) * 1000)
        u = usage or {}
        out = u.get("output")
        inp = u.get("input")
        st = {
            "input": inp, "output": out,
            "cacheRead": u.get("cacheRead"),
            "reasoning": u.get("reasoning"),
            "total": u.get("totalTokens"),
            "cost": (u.get("cost") or {}).get("total"),
            "promptMs": prompt_ms, "genMs": gen_ms,
            # velocidades medidas por reloj, no dadas por pi
            "genTps": round(out / (gen_ms / 1000.0), 1)
                      if out and gen_ms > 0 else None,
            "promptTps": round(inp / (prompt_ms / 1000.0), 1)
                         if inp and prompt_ms > 0 else None,
        }
        return st

    def settle_tools(self):
        """Cierra las herramientas que nunca recibieron su final.

        Pasa cuando pi muere a medias, o cuando el turno acaba sin que
        llegue el `tool_execution_end`. Dejarlas en marcha es mentir: el
        punto sigue parpadeando y nadie va a apagarlo.
        """
        for item in self.log:
            if item.get("kind") == "tool" and item.get("status") == "running":
                self.patch(item, status="stale")

    def emit(self, payload):
        """Thread-safe broadcast."""
        asyncio.run_coroutine_threadsafe(self.broadcast(payload), self.loop)

    async def broadcast(self, payload):
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(payload)
            except Exception:                               # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def push(self, item):
        """Append a transcript item and broadcast it."""
        self.seq += 1
        item["id"] = self.seq
        item["t"] = int(time.time() * 1000)
        if item.get("kind") in ("assistant", "thinking", "tool"):
            self.produced = True
        self.log.append(item)
        self.emit({"type": "item", "item": item})
        return item

    def patch(self, item, **fields):
        item.update(fields)
        self.emit({"type": "patch", "id": item["id"], "fields": fields})

    def drop_last_user(self):
        """Quita del log la ultima burbuja de usuario: un envio deshecho."""
        for i in range(len(self.log) - 1, -1, -1):
            if self.log[i].get("kind") == "user":
                it = self.log[i]
                del self.log[i]
                return it
        return None

    def note(self, level, key, text, **args):
        """Send the key so the browser can say it in its own language.
        `text` travels too, as the fallback for an unknown key."""
        return self.push({"kind": "note", "level": level, "key": key,
                          "args": args, "text": text})

    def push_state(self):
        self.emit({"type": "state", "state": self.state})

    def snapshot(self):
        return {"type": "snapshot", "items": list(self.log),
                "state": self.state, "cwd": self.cwd}

    # ---- events from pi

    def reader(self, proc, gen):
        for line in proc.stdout:
            line = line.rstrip("\r\n")           # LF framing only
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            try:
                self.on_event(ev)
            except Exception as exc:                        # noqa: BLE001
                print("handler:", exc, file=sys.stderr)
        if gen != self.gen:
            return                       # replaced by another project, hush
        self.state["alive"] = False
        self.state["running"] = False
        self.settle_tools()
        self.note("error", "pi_exited", "pi exited. reopen the project.")
        self.push_state()

    def close_think(self):
        """Cierra el bloque de pensamiento abierto y anota cuanto duro."""
        if not self.think:
            return
        secs = int(round(time.time() - self.think_t0)) if self.think_t0 else None
        self.patch(self.think, streaming=False, secs=secs)
        self.think = None
        self.think_t0 = None

    def on_event(self, ev):
        t = ev.get("type")

        if t == "agent_start":
            self.state.update(running=True, startedAt=time.time(), tool=None)
            self.cur = None
            self.prefill_t0 = time.time()
            self.push_state()

        elif t == "message_start":
            m = ev.get("message") or {}
            if m.get("role") == "assistant":
                # la burbuja nace con el primer token: un mensaje que solo
                # trae una herramienta no deja burbuja vacia
                self.cur = None
                self.assistant_open = True
                self.produced = True          # el modelo empieza a responder
                self.gen_first = None
                self.gen_prompt_ms = None
                self.cur_usage = {}
                self.think = None
                self.think_t0 = None

        elif t == "message_update":
            d = ev.get("assistantMessageEvent") or {}
            dt = d.get("type")
            if dt == "text_delta" and self.assistant_open:
                if self.think:            # el texto real cierra el pensamiento
                    self.close_think()
                delta = d.get("delta", "")
                if self.cur is None:
                    self.gen_first = time.time()
                    base = self.prefill_t0 or self.gen_first
                    self.gen_prompt_ms = int(max(0.0,
                        (self.gen_first - base)) * 1000)
                    self.cur = self.push({"kind": "assistant",
                                          "text": delta, "streaming": True})
                else:
                    self.cur["text"] += delta
                    self.emit({"type": "delta", "id": self.cur["id"],
                               "delta": delta})
            elif dt == "thinking_start" and self.assistant_open:
                self.think_t0 = time.time()
            elif dt == "thinking_delta" and self.assistant_open:
                delta = d.get("delta", "")
                if self.think is None:
                    self.think = self.push({"kind": "thinking",
                                            "text": delta, "streaming": True})
                else:
                    self.think["text"] += delta
                    self.emit({"type": "delta", "id": self.think["id"],
                               "delta": delta})
            elif dt == "thinking_end" and self.assistant_open:
                self.close_think()
            u = grab_usage(ev)
            if u:
                self.cur_usage = u

        elif t == "message_end":
            m = ev.get("message") or {}
            if m.get("role") != "assistant":
                return
            if self.think:
                self.close_think()
            text = ""
            c = m.get("content")
            if isinstance(c, str):
                text = c
            else:
                text = "\n".join(b["text"] for b in c or []
                                 if b.get("type") == "text")
            u = grab_usage(ev) or self.cur_usage
            stats = self.build_stats(u)
            self.assistant_open = False
            if self.cur:
                self.patch(self.cur, text=text, streaming=False, stats=stats)
                self.cur = None
            elif text.strip():                # texto sin deltas previos
                self.push({"kind": "assistant", "text": text,
                           "streaming": False, "stats": stats})
            # sin texto y sin burbuja: era un paso de solo herramienta

        elif t == "tool_execution_start":
            self.state["tool"] = ev.get("toolName")
            item = {"kind": "tool", "name": ev.get("toolName"),
                    "args": ev.get("args"), "status": "running",
                    "callId": ev.get("toolCallId")}
            diff = edit_diff(ev.get("args") or {})
            if diff:
                item.update(diff)
            self.push(item)
            self.push_state()

        elif t == "tool_execution_end":
            call = ev.get("toolCallId")
            for item in reversed(self.log):
                if item.get("kind") == "tool" and item.get("callId") == call:
                    content = (ev.get("result") or {}).get("content", [])
                    fields = dict(
                        status="error" if ev.get("isError") else "done",
                        output=text_of(content)[:8000])
                    imgs = images_of(content)      # p.ej. read de una imagen
                    if imgs:
                        fields["images"] = imgs
                    self.patch(item, **fields)
                    break
            self.state["tool"] = None
            self.prefill_t0 = time.time()
            self.push_state()

        elif t == "agent_settled":
            self.state.update(running=False, tool=None)
            self.settle_tools()      # el turno acabo: nada sigue en marcha
            self.push_state()
            self.send_pi({"type": "get_session_stats"})

        elif t == "queue_update":
            self.state["queue"] = {"steering": ev.get("steering", []),
                                   "followUp": ev.get("followUp", [])}
            self.push_state()

        elif t == "compaction_start":
            # el navegador no se enteraba de que pi estaba compactando
            self.compacting = self.note("info", "compacting",
                                        "compacting the context...")

        elif t == "compaction_end":
            r = ev.get("result") or {}
            before, after = r.get("tokensBefore"), r.get("estimatedTokensAfter")
            if self.compacting:               # la misma nota, ahora resuelta
                self.patch(self.compacting, key="compacted",
                           args={"before": before, "after": after},
                           text=f"context compacted: {before} to {after} tokens")
                self.compacting = None
            else:
                self.note("info", "compacted",
                          f"context compacted: {before} to {after} tokens",
                          before=before, after=after)
            window = (self.state.get("context") or {}).get("window")
            self.state["context"] = {
                "tokens": after, "window": window,
                "percent": pct(after, window), "cost": None}
            self.push_state()
            self.poll_stats()                 # y a ver subir el prefill

        elif t == "auto_retry_start":
            self.note("warn", "retrying",
                      f"retrying {ev.get('attempt')}/{ev.get('maxAttempts')}",
                      n=ev.get("attempt"), max=ev.get("maxAttempts"))

        elif t == "extension_error":
            self.note("error", "extension", f"extension: {ev.get('error')}",
                      err=str(ev.get("error")))

        elif t == "extension_ui_request":
            self.on_dialog(ev)

        elif t == "response":
            self.on_response(ev)

    def on_response(self, ev):
        cmd, data = ev.get("command"), ev.get("data") or {}

        if not ev.get("success", True):
            self.note("error", "cmd_failed",
                      f"{cmd} failed: {ev.get('error')}",
                      cmd=cmd, err=str(ev.get("error")))
            return

        if cmd == "get_state":
            self.state.update(
                sessionName=data.get("sessionName"),
                sessionFile=data.get("sessionFile"),
                model=(data.get("model") or {}).get("name"),
                thinking=data.get("thinkingLevel"))
            self.push_state()

        elif cmd == "get_session_stats":
            u = data.get("contextUsage") or {}
            tokens, window = u.get("tokens"), u.get("contextWindow")
            percent = u.get("percent")
            if percent is None:
                percent = pct(tokens, window)
            self.state["context"] = {
                "percent": percent, "tokens": tokens,
                "window": window, "cost": data.get("cost")}
            self.push_state()

        elif cmd in ("switch_session", "new_session"):
            if not data.get("cancelled"):
                self.log.clear()
                self.cur = None
                self.emit({"type": "cleared"})
                self.send_pi({"type": "get_state"})
                self.send_pi({"type": "get_session_stats"})
                self.send_pi({"type": "get_messages"})

        elif cmd == "get_messages":
            self.load_history(data.get("messages"))

        elif cmd == "bash":
            self.push({"kind": "tool", "name": "bash (direct)",
                       "status": "error" if data.get("exitCode") else "done",
                       "output": (data.get("output") or "")[:8000]})

        elif cmd == "export_html":
            self.note("info", "exported", f"exported to {data.get('path')}",
                      path=data.get("path"))

        elif cmd == "set_session_name":
            # pi no avisa del cambio: sin esto la cabecera se queda con el viejo
            self.send_pi({"type": "get_state"})

        elif cmd == "set_model":
            self.state["model"] = data.get("name")
            self.push_state()

        elif cmd == "set_thinking_level":
            # pi no avisa del nuevo nivel: sin esto la cabecera se queda en el
            # viejo (parecia "off" aunque el razonamiento estuviese activo)
            self.send_pi({"type": "get_state"})

        else:
            self.emit({"type": "rpc", "command": cmd, "data": data})

    # ---- history

    def load_history(self, messages):
        """Rebuild the transcript from pi's own messages.

        Built in silence and sent as one snapshot: pushing item by item
        would be a few hundred websocket frames for a long session.
        """
        if messages is None:        # command unsupported: keep what we have
            return
        notes = [i for i in self.log if i.get("kind") == "note"][-4:]
        waiting = [i for i in self.log
                   if i.get("kind") == "ask" and not i.get("answered")]
        self.log.clear()
        self.cur = None
        calls = {}

        def add(item):
            self.seq += 1
            item["id"] = self.seq
            item.setdefault("t", int(time.time() * 1000))
            self.log.append(item)
            return item

        for m in (messages or [])[-HISTORY_CAP:]:
            role = m.get("role")
            stamp = m.get("timestamp")

            if role == "user":
                text = text_of(m.get("content"))
                if text.strip():
                    add({"kind": "user", "text": text, "t": stamp})

            elif role == "assistant":
                for b in m.get("content") or []:
                    kind = b.get("type")
                    if kind == "text" and b.get("text", "").strip():
                        add({"kind": "assistant", "text": b["text"],
                             "streaming": False, "t": stamp})
                    elif kind == "toolCall":
                        item = {"kind": "tool", "name": b.get("name"),
                                "args": b.get("arguments"),
                                "status": "running",
                                "callId": b.get("id"), "t": stamp}
                        diff = edit_diff(b.get("arguments") or {})
                        if diff:
                            item.update(diff)
                        calls[b.get("id")] = add(item)
                    elif kind == "thinking" and b.get("thinking", "").strip():
                        add({"kind": "thinking", "text": b["thinking"],
                             "streaming": False, "t": stamp})

            elif role == "toolResult":
                # half of what a live turn keeps: the whole history
                # travels in one websocket frame
                out = text_of(m.get("content"))[:4000]
                imgs = images_of(m.get("content"))
                status = "error" if m.get("isError") else "done"
                item = calls.get(m.get("toolCallId"))
                if item:
                    item.update(status=status, output=out)
                    if imgs:
                        item["images"] = imgs
                else:                       # result without its call in range
                    it = {"kind": "tool", "name": m.get("toolName"),
                          "status": status, "output": out, "t": stamp}
                    if imgs:
                        it["images"] = imgs
                    add(it)

        for note in notes:                  # recent warnings survive the redraw
            self.log.append(note)
        for item in waiting:                # y pi sigue bloqueado en estos
            self.log.append(item)
        self.emit(self.snapshot())

    # ---- guardrails dialogs

    def on_dialog(self, ev):
        method, rid = ev.get("method"), ev.get("id")

        if method == "notify":
            self.push({"kind": "note",
                       "level": ev.get("notifyType", "info"),
                       "text": ev.get("message", "")})
            return
        if method not in ("select", "confirm", "input", "editor"):
            return

        # un dialogo `select` solo trae titulo y opciones: nunca dice que
        # comando se va a ejecutar. El dato esta en la herramienta que quedo
        # en marcha justo antes, asi que se cuelga de la tarjeta.
        waiting = None
        for it in reversed(self.log):
            if it.get("kind") == "tool" and it.get("status") == "running":
                waiting = it
                break

        item = self.push({
            "kind": "ask", "rid": rid, "method": method,
            "title": ev.get("title") or "Approval needed",
            "body": ev.get("message") or "",
            "options": ev.get("options", []),
            "prefill": ev.get("prefill", ""),
            "tool": waiting.get("name") if waiting else None,
            "detail": tool_gist(waiting.get("args")) if waiting else "",
            "answered": None,
        })
        self.pending[rid] = item["id"]
        self.state["waiting"] = True
        self.push_state()

    def answer(self, rid, payload, label):
        if rid not in self.pending:
            return
        item_id = self.pending.pop(rid)
        for item in self.log:
            if item.get("id") == item_id:
                self.patch(item, answered=label)
                break
        payload.update({"type": "extension_ui_response", "id": rid})
        self.send_pi(payload)
        self.state["waiting"] = bool(self.pending)
        self.push_state()

    # ---- from the browser

    def command(self, msg):
        t = msg.get("type")

        # El cliente los pinta apagados, pero eso es cosmetica: quien no
        # use la pagina manda lo que quiera por el websocket.
        if READ_ONLY and t not in READ_CMDS:
            self.note("warn", "read_only",
                      "read only: set PI_WEB_TOKEN to run anything")
            return

        if t == "answer":
            rid, choice = msg.get("rid"), msg.get("choice")
            if choice == "__cancel__":
                self.answer(rid, {"cancelled": True}, "cancelled")
            elif choice in ("__yes__", "__no__"):
                ok = choice == "__yes__"
                self.answer(rid, {"confirmed": ok}, "yes" if ok else "no")
            else:
                self.answer(rid, {"value": choice}, choice)
            return

        if t == "prompt":
            text = (msg.get("message") or "").strip()
            images = msg.get("images") or []
            if not text and not images:
                return
            if not self.state["running"]:
                self.produced = False        # turno fresco: nada generado aun
            item = {"kind": "user", "text": text}
            if images:
                item["images"] = images
            self.push(item)
            cmd = {"type": "prompt", "message": text}
            if images:
                cmd["images"] = images       # pi acepta images en el prompt
            if self.state["running"]:
                cmd["streamingBehavior"] = msg.get("behavior", "followUp")
            self.send_pi(cmd)
            return

        if t == "steer":
            images = msg.get("images") or []
            item = {"kind": "user", "text": msg.get("message", ""),
                    "steer": True}
            if images:
                item["images"] = images
            self.push(item)
            cmd = {"type": "steer", "message": msg.get("message", "")}
            if images:
                cmd["images"] = images
            self.send_pi(cmd)
            return

        if t == "open_project":
            self.open_project(msg.get("path", ""), msg.get("session"))
            return

        if t == "delete_session":
            why = trash_session(msg.get("path", ""),
                                self.state.get("sessionFile"))
            if why:
                self.note("error", "del_" + why,
                          f"could not remove the session: {why}")
            else:
                self.note("info", "del_ok", "session moved to _trash")
            self.emit({"type": "rpc", "command": "delete_session",
                       "data": {"error": why, "path": msg.get("path", "")}})
            return

        if t == "forget_project":
            path = msg.get("path", "")
            if path.lower() == (self.cwd or "").lower():
                return                       # the open one is not forgettable
            self.state["recent"] = forget(path, self.cwd)
            self.push_state()
            return

        if t == "abort":
            self.send_pi({"type": "abort"})
            # deshacer el envio: solo si el modelo no empezo nada todavia
            if (msg.get("undo") and self.state.get("running")
                    and not self.produced):
                dropped = self.drop_last_user()
                if dropped:
                    self.emit({"type": "drop", "id": dropped["id"],
                               "text": dropped.get("text", ""),
                               "restore": True})
            return

        if t in PASSTHROUGH:
            self.send_pi({k: v for k, v in msg.items() if k != "token"})
            return

        self.emit({"type": "rpc", "command": t,
                   "data": {"error": "command not allowed"}})

    def shutdown(self):
        self.stopped = True
        self.state["alive"] = False
        self.stop_pi()


# --------------------------------------------------------------------- app

bridge: "Bridge | None" = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bridge
    bridge = Bridge(asyncio.get_running_loop())
    print(f"pi-remote {VERSION}  (project: {bridge.cwd or 'none yet'})")
    if READ_ONLY:
        print("PI_WEB_TOKEN is off: read only, nothing can be run")
    else:
        if TOKEN_MADE:
            print("no PI_WEB_TOKEN set: one was made for this run")
        host = socket.gethostname()
        print(f"\n  http://{host}:{PORT}/?token={TOKEN}\n")
    yield
    bridge.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def index():
    if not INDEX.exists():
        return JSONResponse({"error": f"missing {INDEX}"}, status_code=500)
    # no-store: the phone must not keep a stale build while the ui moves
    return FileResponse(INDEX, headers=SAFE_HEADERS)


ICON_DIR = INDEX.parent
MANIFEST = {
    "name": "pi-remote", "short_name": "pi-remote",
    "start_url": "/", "scope": "/",
    # fullscreen oculta la barra de estado en Android; iOS no lo soporta y
    # cae a standalone (se queda su barra). display_override da la cascada.
    "display": "fullscreen",
    "display_override": ["fullscreen", "standalone"],
    "background_color": "#12151a", "theme_color": "#12151a",
    "icons": [
        {"src": "/icons/icon-192.png", "sizes": "192x192",
         "type": "image/png"},
        {"src": "/icons/icon-512.png", "sizes": "512x512",
         "type": "image/png"},
        {"src": "/icons/icon-maskable.png", "sizes": "512x512",
         "type": "image/png", "purpose": "maskable"},
    ],
}


@app.get("/manifest.webmanifest")
async def manifest():
    return JSONResponse(MANIFEST,
                        media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})


@app.get("/icons/{name}")
async def icon(name: str):
    """Sin token: son el cascaron, no datos."""
    f = ICON_DIR / name
    if (name != Path(name).name or not name.startswith("icon")
            or f.suffix != ".png" or not f.is_file()):
        return JSONResponse({"error": "no such icon"}, status_code=404)
    return FileResponse(f, media_type="image/png", headers={
        "Cache-Control": "public, max-age=86400"})


@app.get("/sw.js")
async def service_worker():
    """El worker lleva la VERSION dentro: al subir version, cambia el
    nombre de la cache y el cascaron viejo se purga solo."""
    f = ICON_DIR / "sw.js"
    if not f.is_file():
        return JSONResponse({"error": "no sw"}, status_code=404)
    body = f.read_text(encoding="utf-8").replace("__VERSION__", VERSION)
    return Response(body, media_type="application/javascript", headers={
        "Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/fonts/{name}")
async def font(name: str):
    """No token here: the browser fetches these from css, without the query."""
    f = FONTS / name
    if name != Path(name).name or f.suffix != ".woff2" or not f.is_file():
        return JSONResponse({"error": "no such font"}, status_code=404)
    return FileResponse(f, media_type="font/woff2", headers={
        "Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/api/sessions")
async def sessions(path: str = Query(""), token: str = Query("")):
    """Sessions of `path`, or of the open project when no path is given."""
    if not good_token(token):
        return JSONResponse({"error": "bad token"}, status_code=403)
    cwd = path or bridge.cwd
    if not cwd or not Path(cwd).is_dir():
        return {"dir": "", "sessions": []}
    return {"dir": str(session_dir(cwd)), "sessions": list_sessions(cwd)}


@app.get("/api/browse")
async def browse(path: str = Query(""), token: str = Query("")):
    """Folder cards for the project picker. Starts at the Users folder."""
    if not good_token(token):
        return JSONResponse({"error": "bad token"}, status_code=403)
    root = browse_root()
    try:
        here = Path(path).resolve() if path else root
    except OSError:
        here = root
    if not here.is_dir():
        here = root
    return {"path": str(here), "root": str(root),
            "parent": "" if here == here.parent else str(here.parent),
            "dirs": list_dirs(here), "mark": looks_like_project(here)}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, token: str = Query("")):
    if not good_token(token) or not same_origin(ws):
        await ws.close(code=4003)
        return
    await ws.accept()
    bridge.clients.add(ws)
    await ws.send_json(bridge.snapshot())
    try:
        while True:
            msg = await ws.receive_json()
            bridge.command(msg)
    except (WebSocketDisconnect, ValueError):
        pass
    finally:
        bridge.clients.discard(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning",
                ws_ping_interval=20)
