#!/usr/bin/env python3
"""
Telegram <-> pi (--mode rpc) bridge. Single session.

    set TG_TOKEN=123:ABC
    set TG_CHAT=987654321
    cd C:\\path\\to\\project
    python pi_telegram_bridge.py

Optional env:
    PI_CMD      path to pi        (default: pi)
    PI_RESUME   new | continue    (default: new)
    PI_SESSION  session name      (default: telegram)

Run with --botfather to print the /setcommands block.
Requires: pip install requests
"""

import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path

import requests

TOKEN = os.environ["TG_TOKEN"]
CHAT = int(os.environ["TG_CHAT"])
PI_CMD = os.environ.get("PI_CMD") or shutil.which("pi") or "pi"
RESUME = os.environ.get("PI_RESUME", "new")
SESSION_NAME = os.environ.get("PI_SESSION", "telegram")
API = f"https://api.telegram.org/bot{TOKEN}"

TICK = 4          # seconds between status edits (Telegram throttles below 3)
WORD_ROTATE = 8   # seconds a word stays before another one is picked

WORDS = [
    "Actioning", "Actualizing", "Architecting", "Baking", "Beaming",
    "Beboppin'", "Befuddling", "Billowing", "Blanching", "Bloviating",
    "Boogieing", "Boondoggling", "Booping", "Bootstrapping", "Brewing",
    "Bunning", "Burrowing", "Calculating", "Canoodling", "Caramelizing",
    "Cascading", "Catapulting", "Cerebrating", "Channeling", "Channelling",
    "Choreographing", "Churning", "Clauding", "Coalescing", "Cogitating",
    "Combobulating", "Composing", "Computing", "Concocting", "Considering",
    "Contemplating", "Cooking", "Crafting", "Creating", "Crunching",
    "Crystallizing", "Cultivating", "Deciphering", "Deliberating",
    "Determining", "Dilly-dallying", "Discombobulating", "Doing", "Doodling",
    "Drizzling", "Ebbing", "Effecting", "Elucidating", "Embellishing",
    "Enchanting", "Envisioning", "Evaporating", "Fermenting",
    "Fiddle-faddling", "Finagling", "Flambeing", "Flibbertigibbeting",
    "Flowing", "Flummoxing", "Fluttering", "Forging", "Forming", "Frolicking",
    "Frosting", "Gallivanting", "Galloping", "Garnishing", "Generating",
    "Gesticulating", "Germinating", "Gitifying", "Grooving", "Gusting",
    "Harmonizing", "Hashing", "Hatching", "Herding", "Honking",
    "Hullaballooing", "Hyperspacing", "Ideating", "Imagining", "Improvising",
    "Incubating", "Inferring", "Infusing", "Ionizing", "Jitterbugging",
    "Julienning", "Kneading", "Leavening", "Levitating", "Lollygagging",
    "Manifesting", "Marinating", "Meandering", "Metamorphosing", "Misting",
    "Moonwalking", "Moseying", "Mulling", "Mustering", "Musing", "Nebulizing",
    "Nesting", "Newspapering", "Noodling", "Nucleating", "Orbiting",
    "Orchestrating", "Osmosing", "Perambulating", "Percolating", "Perusing",
    "Philosophising", "Photosynthesizing", "Pollinating", "Pondering",
    "Pontificating", "Pouncing", "Precipitating", "Prestidigitating",
    "Processing", "Proofing", "Propagating", "Puttering", "Puzzling",
    "Quantumizing", "Razzle-dazzling", "Razzmatazzing", "Recombobulating",
    "Reticulating", "Roosting", "Ruminating", "Sauteing", "Scampering",
    "Schlepping", "Scurrying", "Seasoning", "Shenaniganing", "Shimmying",
    "Simmering", "Skedaddling", "Sketching", "Slithering", "Smooshing",
    "Sock-hopping", "Spelunking", "Spinning", "Sprouting", "Stewing",
    "Sublimating", "Swirling", "Swooping", "Symbioting", "Synthesizing",
    "Tempering", "Thinking", "Thundering", "Tinkering", "Tomfoolering",
    "Topsy-turvying", "Transfiguring", "Transmuting", "Twisting",
    "Undulating", "Unfurling", "Unravelling", "Vibing", "Waddling",
    "Wandering", "Warping", "Whatchamacalliting", "Whirlpooling", "Whirring",
    "Whisking", "Wibbling", "Working", "Wrangling", "Zesting", "Zigzagging",
]

HELP = """session
/resume  switch session      /new     start new session
/name    set session name    /fork    branch from a message
/stats   tokens and cost     /compact shrink context
/last    repeat last reply    /export  html transcript
/state   current session info

model
/model   switch model        /think   reasoning level

run
/steer   interrupt with text /abort   stop current turn
/queue   pending messages    /clearq  drop queued
/bash    run command direct  /cwd     working directory

bridge
/pend    open permissions    /ping    bridge alive?
/sessdir session folder      /quit    shut down
/help    this list"""

BOTFATHER = """resume - switch to another session
new - start a new session
name - set session display name
fork - branch from an earlier message
stats - tokens, cost, context usage
state - current session info
compact - shrink the context
last - repeat the last reply
export - export session as html
model - switch model
think - set reasoning level
steer - interrupt with an instruction
abort - stop the current turn
queue - show pending messages
clearq - drop queued messages
bash - run a shell command directly
cwd - show working directory
pend - show open permission dialogs
sessdir - debug the session folder lookup
ping - check the bridge is alive
help - list commands
quit - shut the bridge down"""


# ---------------------------------------------------------------- telegram

def tg(method, **payload):
    try:
        return requests.post(f"{API}/{method}", json=payload, timeout=60).json()
    except requests.RequestException as exc:
        print("telegram:", exc, file=sys.stderr)
        return {}


def md_to_tg(text):
    """Markdown -> Telegram HTML. Only b, i, s, code, pre, a survive."""
    out, parts = [], re.split(r"(```.*?```|`[^`\n]+`)", text, flags=re.S)
    for i, part in enumerate(parts):
        if i % 2:                                   # code, keep verbatim
            if part.startswith("```"):
                body = re.sub(r"^```[a-zA-Z0-9+-]*\n?|```$", "", part)
                out.append(f"<pre>{esc(body.rstrip())}</pre>")
            else:
                out.append(f"<code>{esc(part.strip('`'))}</code>")
            continue

        t = esc(part)
        t = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>",
                   t, flags=re.M)                   # headings -> bold
        t = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", t, flags=re.S)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t, flags=re.S)
        t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])",
                   r"<i>\1</i>", t, flags=re.S)
        t = re.sub(r"(?<![\w_])__(.+?)__(?![\w_])", r"<b>\1</b>", t, flags=re.S)
        t = re.sub(r"~~(.+?)~~", r"<s>\1</s>", t, flags=re.S)
        t = re.sub(r"\[(.+?)\]\((https?://[^\s)]+)\)",
                   r'<a href="\2">\1</a>', t)
        t = re.sub(r"^\s*[-*+]\s+", "\u2022 ", t, flags=re.M)  # bullets
        out.append(t)
    return "".join(out)


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def strip_md(text):
    """Last resort: readable plain text."""
    t = re.sub(r"```[a-zA-Z0-9+-]*\n?|`", "", text)
    t = re.sub(r"\*{1,3}|~~|__", "", t)
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
    return re.sub(r"^\s*[-*+]\s+", "\u2022 ", t, flags=re.M)


def send(text, kb=None, markdown=False):
    raw = text or "(empty)"
    p = {"chat_id": CHAT,
         "text": (md_to_tg(raw) if markdown else raw)[:4000]}
    if markdown:
        p["parse_mode"] = "HTML"
        p["link_preview_options"] = {"is_disabled": True}
    if kb:
        p["reply_markup"] = {"inline_keyboard": kb}
    r = tg("sendMessage", **p)
    if markdown and not r.get("ok"):                # bad entities, retry flat
        print("html rejected:", r.get("description"), file=sys.stderr)
        p.pop("parse_mode", None)
        p["text"] = strip_md(raw)[:4000]
        r = tg("sendMessage", **p)
    return r.get("result", {}).get("message_id")


def send_long(text, markdown=True):
    text = text or "(no text)"
    for chunk in split_chunks(text, 3500):
        send(chunk, markdown=markdown)


def split_chunks(text, size):
    """Split on blank lines when possible, never inside a fenced block."""
    chunks, cur, fence = [], [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fence = not fence
        cur.append(line)
        if not fence and sum(len(x) + 1 for x in cur) > size:
            chunks.append("\n".join(cur))
            cur = []
    if cur:
        chunks.append("\n".join(cur))
    return chunks or [text[:size]]


def send_file(path):
    try:
        with open(path, "rb") as fh:
            requests.post(f"{API}/sendDocument", data={"chat_id": CHAT},
                          files={"document": fh}, timeout=120)
    except (OSError, requests.RequestException) as exc:
        send(f"upload failed: {exc}\n{path}")


def edit(message_id, text, kb=None):
    if not message_id:
        return
    tg("editMessageText", chat_id=CHAT, message_id=message_id,
       text=text[:4000], reply_markup={"inline_keyboard": kb or []})


def drain():
    """Drop updates queued before this run, so an old /quit can't kill us."""
    res = tg("getUpdates", timeout=0, offset=-1).get("result", [])
    return res[-1]["update_id"] + 1 if res else 0


# ------------------------------------------------------------ session files

def sessions_root():
    return Path.home() / ".pi" / "agent" / "sessions"


def _norm(s):
    """Lowercase, every non-alphanumeric run becomes a single dash."""
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


def session_dir():
    """Find pi's folder for this cwd without guessing its slug format."""
    root = sessions_root()
    if not root.is_dir():
        return root
    dirs = [d for d in root.iterdir() if d.is_dir()]
    target = _norm(Path.cwd())
    for d in dirs:                              # exact, normalised
        if _norm(d.name) == target:
            return d
    tail = _norm(Path.cwd().name)               # fallback: folder name only
    matches = [d for d in dirs if tail and tail in _norm(d.name)]
    if len(matches) == 1:
        return matches[0]
    if matches:                                 # several, take the freshest
        return max(matches, key=lambda d: d.stat().st_mtime)
    return root


def session_label(path):
    """Header name, else first user message, else file stem."""
    try:
        with open(path, encoding="utf-8") as fh:
            for _ in range(40):
                line = fh.readline()
                if not line:
                    break
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") == "session" and e.get("name"):
                    return e["name"]
                msg = e.get("message") or {}
                if msg.get("role") == "user":
                    c = msg.get("content")
                    if isinstance(c, str):
                        return c[:45]
                    for blk in c or []:
                        if blk.get("type") == "text":
                            return blk["text"][:45]
    except OSError:
        pass
    return path.stem[:45]


def list_sessions(limit=8):
    d = session_dir()
    if not d.is_dir():
        return []
    files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    return [(f, session_label(f)) for f in files[:limit]]


# ------------------------------------------------------------------- bridge

class Bridge:
    def __init__(self):
        args = [PI_CMD, "--mode", "rpc"]
        if RESUME == "continue":
            args.append("-c")
        else:
            args += ["--name", SESSION_NAME]
        self.proc = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            encoding="utf-8", errors="replace", bufsize=1)

        self.lock = threading.Lock()
        self.streaming = threading.Event()
        self.alive = True
        self.buf = []
        self.tool = None
        self.word = ""
        self.word_t = 0
        self.t0 = 0.0
        self.status_id = None
        self.queue = {"steering": [], "followUp": []}

        self.pending = OrderedDict()   # request id -> {method, options}
        self.cb = {}                   # token -> (kind, payload)
        self.awaiting = None           # request id waiting for typed text
        self.token = 0
        self.named = RESUME == "continue"
        self.first_prompt = ""

    # ---- io

    def send_pi(self, cmd):
        with self.lock:
            self.proc.stdin.write(json.dumps(cmd) + "\n")
            self.proc.stdin.flush()

    def tok(self, kind, payload):
        self.token += 1
        t = str(self.token)
        self.cb[t] = (kind, payload)
        return t

    def shutdown(self, code=0):
        """Close stdin: pi drains its work and exits 0. No EPIPE."""
        self.alive = False
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
        os._exit(code)

    # ---- status line

    def status_text(self):
        secs = int(time.time() - self.t0)
        if self.pending:
            return f"[paused] waiting for permission - {secs}s"
        if secs - self.word_t >= WORD_ROTATE:
            self.word_t = secs
            choices = [w for w in WORDS if w != self.word]
            self.word = random.choice(choices)
        line = f"{self.word}... {secs}s"
        if self.tool:
            line += f"\ntool: {self.tool}"
        return line

    def ticker(self):
        while self.alive:
            time.sleep(TICK)
            if self.status_id and self.streaming.is_set():
                edit(self.status_id, self.status_text())

    # ---- events from pi

    def reader(self):
        for line in self.proc.stdout:
            line = line.rstrip("\r\n")          # LF framing, strip stray CR
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
        self.alive = False
        send("pi exited. restart the bridge.")

    def on_event(self, ev):
        t = ev.get("type")

        if t == "agent_start":
            self.streaming.set()
            self.buf.clear()
            self.tool = None
            self.word = random.choice(WORDS)
            self.word_t = 0
            self.t0 = time.time()
            self.status_id = send(self.status_text())

        elif t == "tool_execution_start":
            self.tool = ev.get("toolName")

        elif t == "message_end":
            m = ev.get("message") or {}
            if m.get("role") == "assistant":
                c = m.get("content")
                if isinstance(c, str):
                    self.buf.append(c)
                else:
                    for blk in c or []:
                        if blk.get("type") == "text":
                            self.buf.append(blk["text"])

        elif t == "agent_settled":
            self.streaming.clear()
            secs = int(time.time() - self.t0)
            edit(self.status_id, f"{self.word} - {secs}s - done")
            self.status_id = None
            send_long("\n".join(x for x in self.buf if x.strip()))
            if not self.named and self.first_prompt:
                self.named = True
                self.send_pi({"type": "set_session_name",
                              "name": f"tg: {self.first_prompt[:40]}"})

        elif t == "queue_update":
            self.queue = {"steering": ev.get("steering", []),
                          "followUp": ev.get("followUp", [])}

        elif t == "compaction_end":
            r = ev.get("result") or {}
            send(f"compacted: {r.get('tokensBefore')} -> "
                 f"{r.get('estimatedTokensAfter')} tokens")

        elif t == "auto_retry_start":
            send(f"retry {ev.get('attempt')}/{ev.get('maxAttempts')}: "
                 f"{str(ev.get('errorMessage', ''))[:200]}")

        elif t == "extension_ui_request":
            self.on_dialog(ev)

        elif t == "extension_error":
            send(f"extension error: {ev.get('error')}")

        elif t == "response":
            self.on_response(ev)

    def on_response(self, ev):
        cmd = ev.get("command")
        data = ev.get("data") or {}

        if not ev.get("success", True):
            send(f"{cmd} failed: {ev.get('error')}")
            return

        if cmd == "get_state":
            send(f"session: {data.get('sessionName') or '(unnamed)'}\n"
                 f"model: {(data.get('model') or {}).get('name')}\n"
                 f"thinking: {data.get('thinkingLevel')}\n"
                 f"messages: {data.get('messageCount')}\n"
                 f"{data.get('sessionFile')}")

        elif cmd == "get_session_stats":
            u = data.get("contextUsage") or {}
            tk = data.get("tokens") or {}
            send(f"context: {u.get('percent')}% "
                 f"({u.get('tokens')}/{u.get('contextWindow')})\n"
                 f"tokens: {tk.get('total')}\n"
                 f"cost: {data.get('cost')}\n"
                 f"tool calls: {data.get('toolCalls')}")

        elif cmd == "get_last_assistant_text":
            send_long(data.get("text") or "(nothing yet)")

        elif cmd == "get_available_models":
            kb = []
            for m in data.get("models", [])[:20]:
                t = self.tok("M", (m.get("provider"), m.get("id")))
                kb.append([{"text": f"{m.get('name')} ({m.get('provider')})",
                            "callback_data": f"M{t}"}])
            send("pick a model", kb) if kb else send("no models")

        elif cmd == "get_available_thinking_levels":
            kb = [[{"text": lv, "callback_data": f"T{self.tok('T', lv)}"}]
                  for lv in data.get("levels", [])]
            send("thinking level", kb) if kb else send("not supported")

        elif cmd == "set_model":
            send(f"model: {data.get('name')}")

        elif cmd == "get_fork_messages":
            kb = []
            for m in data.get("messages", [])[-8:]:
                t = self.tok("F", m.get("entryId"))
                kb.append([{"text": (m.get("text") or "")[:45] or "(empty)",
                            "callback_data": f"F{t}"}])
            send("fork from which message?", kb) if kb else send("nothing to fork")

        elif cmd == "fork":
            send("forked" if not data.get("cancelled") else "fork cancelled")

        elif cmd in ("switch_session", "new_session"):
            if data.get("cancelled"):
                send(f"{cmd} cancelled by an extension")
            else:
                self.named = True
                self.send_pi({"type": "get_state"})

        elif cmd == "bash":
            send_long(f"exit {data.get('exitCode')}\n```\n"
                      f"{data.get('output', '')}\n```", markdown=True)

        elif cmd == "export_html":
            send_file(data.get("path"))

        elif cmd == "clear_queue":
            send(f"dropped: {data.get('steering')} {data.get('followUp')}")

    # ---- guardrails dialogs

    def on_dialog(self, ev):
        method, rid = ev.get("method"), ev.get("id")

        if method == "notify":
            send(ev.get("message", ""))
            return
        if method not in ("select", "confirm", "input", "editor"):
            return

        title = ev.get("title") or "confirm"
        body = ev.get("message") or ""
        opts = ev.get("options", [])
        self.pending[rid] = {"method": method, "options": opts}

        if method == "select":
            kb = [[{"text": o, "callback_data": f"P{self.tok('P', (rid, i))}"}]
                  for i, o in enumerate(opts)]
            kb.append([{"text": "cancel",
                        "callback_data": f"P{self.tok('P', (rid, 'x'))}"}])
            send(f"PERMISSION\n{title}\n{body}".strip(), kb)

        elif method == "confirm":
            row = [{"text": lbl,
                    "callback_data": f"P{self.tok('P', (rid, v))}"}
                   for lbl, v in (("yes", "y"), ("no", "n"))]
            send(f"PERMISSION\n{title}\n{body}".strip(), [row])

        else:
            self.awaiting = rid
            send(f"{title}\n{body}\nreply with text, or /cancel".strip())

        if self.status_id:
            edit(self.status_id, self.status_text())

    def answer_dialog(self, rid, payload):
        self.pending.pop(rid, None)
        for t in [k for k, v in self.cb.items()
                  if v[0] == "P" and v[1][0] == rid]:
            self.cb.pop(t, None)
        payload.update({"type": "extension_ui_response", "id": rid})
        self.send_pi(payload)
        if self.status_id:
            edit(self.status_id, self.status_text())

    # ---- telegram input

    def on_callback(self, cq):
        tg("answerCallbackQuery", callback_query_id=cq["id"])
        data = cq.get("data", "")
        entry = self.cb.get(data[1:])
        if not entry:
            return
        kind, payload = entry

        if kind == "P":
            rid, choice = payload
            if rid not in self.pending:
                return
            meta = self.pending[rid]
            if choice == "x":
                self.answer_dialog(rid, {"cancelled": True})
                send("cancelled")
            elif meta["method"] == "confirm":
                ok = choice == "y"
                self.answer_dialog(rid, {"confirmed": ok})
                send("yes" if ok else "no")
            else:
                opt = meta["options"][int(choice)]
                self.answer_dialog(rid, {"value": opt})
                send(f"chose: {opt}")

        elif kind == "S":
            self.send_pi({"type": "switch_session", "sessionPath": payload})

        elif kind == "M":
            provider, model_id = payload
            self.send_pi({"type": "set_model", "provider": provider,
                          "modelId": model_id})

        elif kind == "T":
            self.send_pi({"type": "set_thinking_level", "level": payload})
            send(f"thinking: {payload}")

        elif kind == "F":
            self.send_pi({"type": "fork", "entryId": payload})

    def on_text(self, text):
        text = text.strip()
        arg = text.split(" ", 1)[1].strip() if " " in text else ""

        if self.awaiting:
            rid, self.awaiting = self.awaiting, None
            self.answer_dialog(
                rid,
                {"cancelled": True} if text == "/cancel" else {"value": text})
            return

        if not text.startswith("/"):
            if not self.first_prompt:
                self.first_prompt = text
            cmd = {"type": "prompt", "message": text}
            if self.streaming.is_set():
                cmd["streamingBehavior"] = "followUp"
            self.send_pi(cmd)
            return

        head = text.split(" ", 1)[0]

        if head == "/help":
            send(HELP)
        elif head == "/ping":
            send(f"alive - streaming={self.streaming.is_set()} "
                 f"- pending={len(self.pending)}")
        elif head == "/cwd":
            send(str(Path.cwd()))
        elif head == "/pend":
            if not self.pending:
                send("nothing waiting")
            for rid, m in self.pending.items():
                send(f"{rid[:8]} {m['method']} {m['options']}")
        elif head == "/queue":
            send(f"steering: {self.queue['steering']}\n"
                 f"followUp: {self.queue['followUp']}")

        elif head == "/sessdir":
            root = sessions_root()
            names = ([d.name for d in root.iterdir() if d.is_dir()]
                     if root.is_dir() else [])
            send(f"cwd: {Path.cwd()}\nresolved: {session_dir()}\n"
                 f"files: {len(list_sessions(99))}\n\ncandidates:\n"
                 + ("\n".join(names) or "(none)"))

        elif head == "/resume":
            items = list_sessions()
            if not items:
                send(f"no sessions found in\n{session_dir()}")
            else:
                kb = [[{"text": lbl,
                        "callback_data": f"S{self.tok('S', str(f))}"}]
                      for f, lbl in items]
                send("pick a session", kb)
        elif head == "/name":
            if arg:
                self.named = True
                self.send_pi({"type": "set_session_name", "name": arg})
                send(f"named: {arg}")
            else:
                send("usage: /name some label")
        elif head == "/new":
            self.send_pi({"type": "new_session"})
            self.named = False
            self.first_prompt = ""
        elif head == "/fork":
            self.send_pi({"type": "get_fork_messages"})
        elif head == "/stats":
            self.send_pi({"type": "get_session_stats"})
        elif head == "/state":
            self.send_pi({"type": "get_state"})
        elif head == "/compact":
            self.send_pi({"type": "compact"})
        elif head == "/last":
            self.send_pi({"type": "get_last_assistant_text"})
        elif head == "/export":
            self.send_pi({"type": "export_html"})

        elif head == "/model":
            self.send_pi({"type": "get_available_models"})
        elif head == "/think":
            self.send_pi({"type": "get_available_thinking_levels"})

        elif head == "/steer":
            if arg:
                self.send_pi({"type": "steer", "message": arg})
            else:
                send("usage: /steer do it differently")
        elif head == "/abort":
            self.send_pi({"type": "abort"})
        elif head == "/clearq":
            self.send_pi({"type": "clear_queue"})
        elif head == "/bash":
            if arg:
                self.send_pi({"type": "bash", "id": "tg", "command": arg})
            else:
                send("usage: /bash git status")

        elif head == "/quit":
            send("bye")
            self.shutdown()
        else:
            send("unknown command\n" + HELP)

    def poller(self):
        offset = drain()
        while self.alive:
            r = tg("getUpdates", offset=offset, timeout=30,
                   allowed_updates=["message", "callback_query"])
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                if "callback_query" in u:
                    cq = u["callback_query"]
                    if cq["from"]["id"] == CHAT:
                        self.on_callback(cq)
                    continue
                msg = u.get("message") or {}
                if msg.get("chat", {}).get("id") != CHAT:
                    continue                      # hard filter, keep it
                if msg.get("text"):
                    self.on_text(msg["text"])


def main():
    b = Bridge()
    threading.Thread(target=b.reader, daemon=True).start()
    threading.Thread(target=b.ticker, daemon=True).start()
    send(f"bridge up - {Path.cwd()}\n\n{HELP}")
    try:
        b.poller()
    except KeyboardInterrupt:
        print("\nstopping", file=sys.stderr)
        b.shutdown()
    except Exception:                                       # noqa: BLE001
        import traceback
        traceback.print_exc()
        try:
            send("bridge crashed, see the terminal")
        except Exception:                                   # noqa: BLE001
            pass
        b.shutdown(1)


if __name__ == "__main__":
    if "--botfather" in sys.argv:
        print(BOTFATHER)
    else:
        main()
