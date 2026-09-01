# pi-remote

Drive the [pi coding agent](https://pi.dev) from your phone, on **native
Windows**, with nothing in between. One Python process wraps `pi --mode rpc`
and serves a web app over your tailnet. No daemon, no Unix socket, no relay,
no third party: your browser talks to your own machine.

<!-- CAPTURA 1 — la principal, la que se ve en GitHub sin hacer scroll.
     Un turno completo en el móvil, tema oscuro: tu burbuja arriba a la
     derecha, la respuesta a ancho completo con un bloque de código, una
     fila de herramienta y, abajo, la tarjeta ámbar de permiso.
     Ancho ~400px. -->

> **Whoever reaches this port can run commands on your machine.** There is no
> sandbox: the bridge starts a real agent in a real folder. Set `PI_WEB_TOKEN`,
> and only expose it inside your tailnet. Read [Security](#security) before
> leaving it running.

## Why this exists

The agent has to run where the code is. If your code lives on Windows, the
existing options do not fit:

| | runs on native Windows | transcript stays home |
|---|---|---|
| [pi-web](https://github.com/jmfederico/pi-web) | no, WSL only | yes |
| [remote-pi](https://github.com/jacobaraujo7/remote_pi) | needs a relay | self-hosted relay |
| [pi-remote-control](https://github.com/CleverCloud/pi-remote-control) | via a hosted relay | no |
| Telegram bridges | yes | no |
| **this** | **yes** | **yes** |

The ones that keep everything at home assume a daemon plus a Unix domain
socket, which is exactly what Windows does not have.

## Install

```bash
pip install -r requirements.txt
cd C:\path\to\your\project
python pi_web_bridge.py
```

Open `http://<your-machine>:8770`. Over Tailscale, use the tailnet name.
Keep the `static/` folder next to the script: it holds the page, the icons and
the fonts, all served locally so the page never calls out to anyone.

| Variable | Default | Meaning |
|---|---|---|
| `PI_CMD` | auto-detected | path to the pi executable |
| `PI_RESUME` | `new` | `continue` picks up the latest session here |
| `PI_SESSION` | `web` | session name for a fresh session |
| `PI_WEB_HOST` | `0.0.0.0` | bind address |
| `PI_WEB_PORT` | `8770` | port |
| `PI_WEB_TOKEN` | none | shared secret, appended as `?token=` |
| `PI_WEB_ORIGINS` | none | extra allowed `Origin`s, comma separated |
| `PI_WEB_CWD` | none | project to open at startup |
| `PI_WEB_STATE` | `state.json` | where recent projects are kept |
| `PI_WEB_LOG` | `bridge.log` | log file when there is no console |

## Leave it running

The bridge is a server, not a terminal app, so it does not need a console at
all. The goal is not to recover it after closing the terminal: it is to never
be a child of one. Nothing extra to install — every option below is a feature
of the operating system.

### Windows

Three ways, least invasive first.

**1. Startup folder — start here.** Press `Win`+`R`, type `shell:startup`, and
drop a shortcut in it:

```
Target:      C:\Path\To\pythonw.exe  C:\Path\To\pi_web_bridge.py
Start in:    C:\Path\To\pi-remote
```

`pythonw.exe` is Python without a console, so there is no window and no
terminal to close; the log goes to `bridge.log`. It starts with your session
and keeps running. Two minutes, nothing registered, nothing to undo but
deleting the shortcut.

**2. Task Scheduler — if you want it to come back after a crash.** The startup
folder starts the bridge; it does not restart it. A task does. The cost is
that Task Scheduler was built for short maintenance jobs, not for long-lived
servers, and its defaults reflect that. Four settings decide whether this
survives:

| Setting | Why |
|---|---|
| `ExecutionTimeLimit` = `PT0S` | **Tasks stop after 72 hours by default.** Without this the bridge dies after three days with no clue why |
| Uncheck both battery options | Otherwise a laptop kills the bridge the moment you unplug it |
| *Only when the user is logged on* | The other choice runs in session 0, cut off from your desktop |
| A 30 s delay, and *restart if the task fails* | So Tailscale is up first, and a crash is not the end |

Trigger *at log on*, action `pythonw.exe` with the script, *start in* the
project folder. The four settings above are only reachable from the task's
properties or from an XML definition — the quick `schtasks` one-liner cannot
set them.

**3. A real Windows service.** Possible with NSSM or `pywin32`, and not
recommended here: both add an external dependency to a project whose whole
point is that it has almost none. The first two options already give you
everything a service would.

### Linux — systemd user service

`~/.config/systemd/user/pi-remote.service`:

```ini
[Unit]
Description=pi-remote bridge

[Service]
ExecStart=/usr/bin/python3 %h/pi-remote/pi_web_bridge.py
WorkingDirectory=%h/pi-remote
Restart=always
Environment=PI_WEB_TOKEN=...

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now pi-remote
loginctl enable-linger $USER      # survives logging out
```

No traps here: `Restart=always` does what it says and there is no time limit.

### macOS — launchd

A plist in `~/Library/LaunchAgents/dev.pi-remote.plist` with `RunAtLoad` and
`KeepAlive` set to `true`, `ProgramArguments` pointing at python3 and the
script, then `launchctl load ~/Library/LaunchAgents/dev.pi-remote.plist`.
Same behaviour as systemd: starts on login, comes back if it dies.

### By hand

`pythonw pi_web_bridge.py` on Windows, `nohup python3 pi_web_bridge.py &`
elsewhere. Survives closing the terminal, but not a reboot.

### Whichever you choose

The machine has to stay awake. A laptop that suspends takes the bridge with
it, and no amount of configuration fixes that — check your power plan.

> Running unattended means nobody reads the console. That is why a missing
> token is also announced **on the page itself**, in a red strip under the
> header — once per browser, so it warns without becoming wallpaper. The
> current state is always in *about*.

## Projects and sessions

The bridge starts with no project. Pick a folder and it launches pi there;
the choice is remembered, so after a restart it comes back where you left off.

<!-- CAPTURA 2 — la barra lateral abierta con tres o cuatro proyectos, uno
     de ellos desplegado mostrando "sesión nueva" en ámbar y sus sesiones
     con fecha. Usa nombres genéricos, no los de tus proyectos reales. -->

- **Tap a project** to unfold its sessions. Tap a session to open exactly that
  one; tap *new session* to start a fresh one in that folder.
- **Hold a project or a session** for a dialog with its actions.
- Removing a session does not delete it: pi has no delete over RPC, so the
  `.jsonl` is moved to a `_trash` folder beside it. The open session is
  refused.

<!-- CAPTURA 3 — el selector de carpetas: tarjetas desde C:\Users, con la
     flecha de subir arriba y el botón ámbar "usar esta carpeta". -->

Opening a project rebuilds the transcript from pi's own `get_messages`, so the
history is the real session on disk, not something kept in memory.

## Permission dialogs

This is the part worth understanding, because it is where a remote agent
becomes safe to use.

pi ships **no permission prompts of its own**. Without a guardrails extension
installed, the agent runs whatever it decides to run. With one, the extension
asks, and that question arrives here as an `extension_ui_request` that
**blocks the turn until you answer** — indefinitely, since `pi-guardrails`
sets no timeout.

<!-- CAPTURA 4 — la tarjeta de permiso ampliada: cabecera "pi pregunta",
     el título de la extensión, la caja con la frase en cristiano y sus
     avisos, el comando en monoespaciada debajo, y los botones con las
     opciones reales. Y una segunda, ya respondida, con el check verde y
     "respondido: permitir una vez". -->

Four things that are easy to get wrong, and that this bridge handles:

- **A permission is not yes or no.** A `select` dialog carries the extension's
  real options — allow once, allow for the session, deny — and they are shown
  as they come, never invented.
- **It says what the command will do, in plain words.** A `select` dialog only
  carries a title and the options: never the command. So the bridge pairs it
  with the tool call left running, and the page reads that command and says it
  out loud — *deletes /tmp/sv_src*, `and everything inside`, `without asking`.
  It is a lookup table, not a model: it never calls out, never guesses, and
  what it does not recognise it simply names.
- **While pi waits for you it is not working.** The readout bar disappears and
  leaves the screen to the approval card, so a blocked turn never looks like a
  busy one.
- **`notify` and `setStatus` need no answer** and are shown as plain notes.

The four dialog kinds — `select`, `confirm`, `input`, `editor` — are all
answered from the browser.

<!-- CAPTURA 5 — la barra de lectura mientras genera: la palabra rotatoria
     junto al cursor dentro del mensaje, y abajo el medidor de contexto con
     "56.79% | 56k/131k" y el botón de parar. -->

## Commands

Type `/` or tap the button inside the composer. Twenty-two commands, filtered
as you type, with keyboard navigation on a desktop browser.

<!-- CAPTURA 6 — el diálogo de ayuda con la lista de comandos y su
     descripción, sobre el fondo desenfocado. -->

The ones that cannot be undone — `/compact`, `/clearq`, `/new` — ask first.
`/bash` runs a command **skipping the model entirely**, and with it the
guardrails: it is your hand, not the agent's.

## Look and language

Two themes and two languages (English and Spanish), picked from the menu and
remembered per browser. Fonts, icons and everything else are served by the
bridge, so the page works on a tailnet with no route to the internet.

<!-- CAPTURA 7 — el menú de ajustes: apariencia con auto/claro/oscuro, la
     tarjeta de idioma, y ayuda / acerca de / donar. Una en cada tema, lado
     a lado, estaría bien. -->

## Security

- Without `PI_WEB_TOKEN` anyone who can reach the port can drive the agent.
  On a tailnet that is usually the point; on a LAN it usually is not.
- The WebSocket checks `Origin`, because WebSockets ignore the same-origin
  policy: any page you visit could otherwise open one against your tailnet.
  Behind a proxy such as `tailscale serve` the origin no longer matches the
  host, so set `PI_WEB_ORIGINS`.
- The page ships a strict CSP, `nosniff` and `no-referrer`, and the token is
  compared in constant time.
- pi ships no permission prompts of its own. Install a guardrails extension.

## How it works

```
browser  <--WebSocket-->  pi_web_bridge.py  <--stdin/stdout JSONL-->  pi --mode rpc
```

The script spawns `pi --mode rpc` and owns its stdin and stdout. Events
(`agent_start`, `message_update`, `tool_execution_*`, `agent_settled`) become
messages to you; what you send becomes `prompt`, `steer` or `abort` commands.

It cannot attach to a pi already running in a terminal: a process has one
stdin. What is shared is the session file on disk, so a session started in the
terminal can be opened here and the other way round. One writer at a time.

## Testing without a model

`tests/fake_pi.py` speaks enough of the RPC protocol to exercise everything:
streaming, tool calls, a permission dialog that blocks until answered, and
`get_messages` for history. No API key and no model needed.

```bash
python tests/run.py            # everything, about 80 seconds
python tests/run.py rail       # just the ones matching "rail"
```

Sixteen checks: the page is driven in a real headless Chrome through the
DevTools protocol, which is how the animation, contrast, layout and security
checks are measured rather than assumed. Chrome or Edge is found
automatically; point `CHROME` at it otherwise.

## License

MIT. See [LICENSE](LICENSE).

Third-party components: FastAPI (MIT), Uvicorn and Starlette (BSD-3-Clause),
Material Icons (Apache-2.0), IBM Plex Mono and Plus Jakarta Sans (OFL-1.1).
