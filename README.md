# pi-remote

Two ways to drive the [pi coding agent](https://pi.dev) from your phone:
a Telegram bot and a self-hosted web app. Both wrap `pi --mode rpc` and speak
its JSONL protocol, so the agent runs on your machine and keeps its session.

Both handle guardrail prompts. When an extension asks whether pi may run a
command or touch a file outside the workspace, the question reaches you with
its real options, and your answer goes back to the agent.

| | `pi_telegram_bridge.py` | `pi_web_bridge.py` |
|---|---|---|
| Setup | a bot token, nothing to host | one Python process |
| Reach | anywhere Telegram works | your tailnet or LAN |
| Data | transcript passes through Telegram | never leaves your network |
| Streaming | reply arrives when the turn ends | token by token |
| Deps | `requests` | `fastapi`, `uvicorn` |

## Web bridge

```bash
pip install fastapi "uvicorn[standard]"
cd /path/to/your/project
python pi_web_bridge.py
```

Open `http://<your-machine>:8770`. Over Tailscale, use the tailnet name.
Keep the `static/` folder next to the script: it holds the page, the icons
and the fonts, all served locally so the page never calls out to anyone.

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

Without `PI_WEB_TOKEN`, anyone who can reach the port can drive the agent.
On a tailnet that is usually the point; on a LAN it usually is not.

## Telegram bridge

```bash
pip install requests
export TG_TOKEN=...      # from @BotFather
export TG_CHAT=...       # your numeric chat id
cd /path/to/your/project
python pi_telegram_bridge.py
```

`python pi_telegram_bridge.py --botfather` prints a command list you can paste
into BotFather's `/setcommands`.

The bridge only accepts messages from `TG_CHAT`. Do not remove that check:
whoever can message the bot can run shell commands on your machine.

## How it works

The script spawns `pi --mode rpc` and owns its stdin and stdout. Events
(`agent_start`, `message_update`, `tool_execution_*`, `agent_settled`) become
messages to you; what you send becomes `prompt`, `steer` or `abort` commands.
Guardrail dialogs arrive as `extension_ui_request` and block the turn until an
`extension_ui_response` with the matching id comes back.

Sessions are pi's own JSONL files under `~/.pi/agent/sessions/`, so a session
started in the terminal can be resumed here and the other way round. One
process at a time per session file: two writers corrupt the history.

## Caveats

- The bridge starts its own agent. It cannot attach to a pi already running in
  a terminal, because a process has one stdin.
- The WebSocket checks `Origin`, because WebSockets ignore the same-origin
  policy. Behind a proxy such as `tailscale serve` the origin no longer matches
  the host, so set `PI_WEB_ORIGINS`.
- pi cannot delete sessions over RPC. "Remove session" moves the `.jsonl` into a
  `_trash` folder beside it; nothing is erased, and the open session is refused.
- pi ships no permission prompts of its own. Install a guardrails extension, or
  the bridge will happily run whatever the model decides to run.
- `/bash` and the shell command in the web menu bypass the model entirely, and
  the guardrail extensions with it.
- `session_dir()` locates pi's folder for the current directory by normalising
  names. If session listing comes up empty, the Telegram bridge has `/sessdir`
  to show what it found.

## Testing without a model

`fake_pi.py` speaks enough of the RPC protocol to exercise both bridges:
streaming, a tool call, a permission dialog that blocks until answered, and
`get_messages` for history.

`test_web_bridge.py` and `test_palette.js` still point at a Linux sandbox and do
not run on Windows yet.

## License

MIT.
