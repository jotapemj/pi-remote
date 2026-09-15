#!/usr/bin/env python3
"""Fake pi --mode rpc. Emits a realistic event stream so the bridges can be
tested without a model. Not part of the project, just a harness."""
import json
import sys
import threading
import time

def out(o):
    sys.stdout.write(json.dumps(o) + "\n")
    sys.stdout.flush()

USAGE = {"input": 12000, "output": 240, "cacheRead": 0, "cacheWrite": 0,
         "reasoning": 30, "totalTokens": 12270, "cost": {"total": 0}}

PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP8"
           "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

def say(chunks, final):
    out({"type": "message_start",
         "message": {"role": "assistant", "content": []}})
    time.sleep(0.3)
    for c in chunks:
        time.sleep(0.1)
        out({"type": "message_update", "usage": {},
             "assistantMessageEvent": {"type": "text_delta",
                                       "contentIndex": 0, "delta": c}})
    out({"type": "message_end", "message": {
        "role": "assistant",
        "content": [{"type": "text", "text": final}], "usage": USAGE}})

def tool_only(call, name, args):
    """Un paso que solo lanza una herramienta: mensaje de asistente sin
    texto, envolviendo la llamada. Es el que dejaba burbuja vacia."""
    out({"type": "message_start",
         "message": {"role": "assistant", "content": []}})
    out({"type": "tool_execution_start", "toolCallId": call,
         "toolName": name, "args": args})
    time.sleep(0.15)
    out({"type": "tool_execution_end", "toolCallId": call, "toolName": name,
         "result": {"content": [{"type": "text", "text": "ok"}]},
         "isError": False})
    out({"type": "message_end", "message": {
        "role": "assistant",
        "content": [{"type": "toolCall", "id": call, "name": name}],
        "usage": USAGE}})

def multi_turn():
    out({"type": "agent_start"})
    say(["Verifico ", "cuando cambio."], "Verifico cuando cambio.")
    for i in range(3):
        tool_only("m%d" % i, "ctx_execute",
                  {"code": "import subprocess, os  # paso %d" % i})
    say(["Listo, ", "era static."], "Listo, era static.")
    out({"type": "agent_end", "messages": [], "willRetry": False})
    out({"type": "agent_settled"})

def think_turn():
    """Un turno que razona antes de hablar: thinking_start/delta/end y luego
    el texto. El puente debe volverlo un item plegable con su duracion."""
    out({"type": "agent_start"})
    out({"type": "message_start",
         "message": {"role": "assistant", "content": []}})
    out({"type": "message_update", "usage": {},
         "assistantMessageEvent": {"type": "thinking_start", "contentIndex": 0}})
    reason = ["El usuario ", "pregunta algo. ", "Reviso y decido."]
    for c in reason:
        time.sleep(0.1)
        out({"type": "message_update", "usage": {},
             "assistantMessageEvent": {"type": "thinking_delta",
                                       "contentIndex": 0, "delta": c}})
    full = "".join(reason)
    out({"type": "message_update", "usage": {},
         "assistantMessageEvent": {"type": "thinking_end",
                                   "contentIndex": 0, "content": full}})
    for c in ["La ", "respuesta clara."]:
        time.sleep(0.1)
        out({"type": "message_update", "usage": {},
             "assistantMessageEvent": {"type": "text_delta",
                                       "contentIndex": 1, "delta": c}})
    out({"type": "message_end", "message": {
        "role": "assistant",
        "content": [{"type": "thinking", "thinking": full},
                    {"type": "text", "text": "La respuesta clara."}],
        "usage": USAGE}})
    out({"type": "agent_end", "messages": [], "willRetry": False})
    out({"type": "agent_settled"})


ABORT = threading.Event()


def stoppable_turn():
    """Piensa despacio (~3 s). Si llega abort, para EN SECO sin generar texto
    (agent_settled y fuera): asi el puente puede pedir el resumen aparte. Si
    termina el pensamiento, cierra con 'Listo.'."""
    out({"type": "agent_start"})
    out({"type": "message_start",
         "message": {"role": "assistant", "content": []}})
    out({"type": "message_update", "usage": {},
         "assistantMessageEvent": {"type": "thinking_start", "contentIndex": 0}})
    full = ""
    for _ in range(60):
        if ABORT.is_set():
            out({"type": "agent_settled"})       # interrumpido: sin texto
            return
        c = "reviso. "
        full += c
        out({"type": "message_update", "usage": {},
             "assistantMessageEvent": {"type": "thinking_delta",
                                       "contentIndex": 0, "delta": c}})
        time.sleep(0.05)
    out({"type": "message_update", "usage": {},
         "assistantMessageEvent": {"type": "thinking_end",
                                   "contentIndex": 0, "content": full}})
    out({"type": "message_update", "usage": {},
         "assistantMessageEvent": {"type": "text_delta",
                                   "contentIndex": 1, "delta": "Listo."}})
    out({"type": "message_end", "message": {
        "role": "assistant",
        "content": [{"type": "thinking", "thinking": full},
                    {"type": "text", "text": "Listo."}],
        "usage": USAGE}})
    out({"type": "agent_end", "messages": [], "willRetry": False})
    out({"type": "agent_settled"})


def summary_turn():
    """El resumen al parar: el puente lo pide con un prompt tras abortar. Una
    sola linea: confirmacion + estaba + lo que hacia."""
    out({"type": "agent_start"})
    say(["Vale, paro. Estaba revisando la configuracion del proyecto."],
        "Vale, paro. Estaba revisando la configuracion del proyecto.")
    out({"type": "agent_end", "messages": [], "willRetry": False})
    out({"type": "agent_settled"})


def slow_turn(text):
    """Arranca el turno pero se demora antes de generar: es la ventana para
    deshacer el envio. Si llega abort en esa pausa, para sin generar nada."""
    out({"type": "agent_start"})
    for _ in range(40):                  # ~2 s de margen, revisando el abort
        if ABORT.is_set():
            out({"type": "agent_settled"})
            return
        time.sleep(0.05)
    say(["Ya ", "voy."], "Ya voy.")
    out({"type": "agent_end", "messages": [], "willRetry": False})
    out({"type": "agent_settled"})


def image_turn(nimg):
    """Confirma cuantas imagenes llegaron: prueba el passthrough del puente."""
    plural = "es" if nimg != 1 else ""
    out({"type": "agent_start"})
    say(["Veo ", "%d imagen%s." % (nimg, plural)],
        "Veo %d imagen%s." % (nimg, plural))
    out({"type": "agent_end", "messages": [], "willRetry": False})
    out({"type": "agent_settled"})


def readimg_turn():
    """Una herramienta `read` que devuelve una imagen: prueba que el puente
    reenvia el ImageContent del tool result al cliente."""
    call = "cimg"
    out({"type": "agent_start"})
    out({"type": "message_start",
         "message": {"role": "assistant", "content": []}})
    out({"type": "tool_execution_start", "toolCallId": call,
         "toolName": "read", "args": {"path": "shot.png"}})
    time.sleep(0.15)
    out({"type": "tool_execution_end", "toolCallId": call, "toolName": "read",
         "result": {"content": [
             {"type": "text", "text": "Read image file [image/png]"},
             {"type": "image", "data": PNG_B64, "mimeType": "image/png"}]},
         "isError": False})
    out({"type": "message_end", "message": {
        "role": "assistant",
        "content": [{"type": "toolCall", "id": call, "name": "read"}],
        "usage": USAGE}})
    out({"type": "agent_end", "messages": [], "willRetry": False})
    out({"type": "agent_settled"})


def turn(text, nimg=0):
    if nimg:
        image_turn(nimg)
        return
    if "readimg" in text:
        readimg_turn()
        return
    if "genrate" in text:     # mide el tk/s: stream corto + cola larga tras el
        out({"type": "agent_start"})   # ultimo token (el bug contaba la cola)
        out({"type": "message_start",
             "message": {"role": "assistant", "content": []}})
        for _ in range(10):
            out({"type": "message_update", "assistantMessageEvent":
                 {"type": "text_delta", "contentIndex": 0, "delta": "tok "}})
            time.sleep(0.1)            # ~1s de streaming real
        time.sleep(2.0)               # cola: pi finaliza / prepara la siguiente
        out({"type": "message_end", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "tok " * 10}],
            "usage": {"input": 100, "output": 50, "totalTokens": 150,
                      "reasoning": 0, "cost": {"total": 0}}}})
        out({"type": "agent_end", "messages": [], "willRetry": False})
        out({"type": "agent_settled"})
        return
    if "<hint:" in text:      # el puente inyecto la instruccion de sugerencia
        out({"type": "agent_start"})
        # el marcador se streamea como un chunk mas (el pi real lo genera token
        # a token, no aparte): asi el cliente lo ve llegar y lo stripea
        say(["Hecho. ", "Cuando digas, push.",
             "\n<hint: Vale, haz el push.>",
             "\n<hint: Espera, revisa antes.>",
             "\n<hint: Muestrame el diff.>"],
            "Hecho. Cuando digas, push.\n<hint: Vale, haz el push.>"
            "\n<hint: Espera, revisa antes.>\n<hint: Muestrame el diff.>")
        out({"type": "agent_end", "messages": [], "willRetry": False})
        out({"type": "agent_settled"})
        return
    if "slow" in text:
        slow_turn(text)
        return
    if "stopme" in text:
        stoppable_turn()
        return
    if "interrupted" in text:        # el puente pide el resumen tras abortar
        summary_turn()
        return
    if "multi" in text:
        multi_turn()
        return
    if "think" in text:
        think_turn()
        return
    out({"type": "agent_start"})
    out({"type": "message_start", "message": {"role": "assistant", "content": []}})
    time.sleep(0.4)                      # prefill: tiempo hasta el primer token
    for chunk in ["Looking at ", "**that** now.\n\n", "Here is `code`:\n",
                  "```py\nx = 5 < 6\n```\n"]:
        time.sleep(0.15)
        out({"type": "message_update", "usage": {},
             "assistantMessageEvent": {"type": "text_delta",
                                       "contentIndex": 0, "delta": chunk}})
    out({"type": "tool_execution_start", "toolCallId": "c0",
         "toolName": "edit",
         "args": {"path": "app/main.py", "edits": [
             {"oldText": "def run():\n    print('viejo')\n    return 1",
              "newText": "def run():\n    print('nuevo')\n"
                         "    log('ok')\n    return 0"}]}})
    out({"type": "tool_execution_end", "toolCallId": "c0", "toolName": "edit",
         "result": {"content": [{"type": "text", "text": "1 edit applied"}]},
         "isError": False})
    out({"type": "tool_execution_start", "toolCallId": "c1",
         "toolName": "bash", "args": {"command": "ls -la"}})
    time.sleep(0.3)
    out({"type": "tool_execution_end", "toolCallId": "c1", "toolName": "bash",
         "result": {"content": [{"type": "text", "text": "total 48\ndrwx 4 x"}]},
         "isError": False})
    if "compact" in text:
        global TOKENS
        out({"type": "compaction_start"})
        time.sleep(0.3)
        before = TOKENS
        out({"type": "compaction_end",
             "result": {"tokensBefore": before,
                        "estimatedTokensAfter": 5200}})
        TOKENS = 5200
        # el prefill rehace el contexto y sube en un par de pasos, como el
        # de verdad: la barra tiene que ir subiendo con la rafaga de sondeos
        def refill():
            global TOKENS
            for v in (11000, 16000):
                time.sleep(1.8)
                TOKENS = v
        threading.Thread(target=refill, daemon=True).start()
        finish()
        return
    if "danger" in text:
        # la herramienta se queda en marcha mientras se pide permiso:
        # es de ahi de donde el puente saca que comando va a ejecutarse
        out({"type": "tool_execution_start", "toolCallId": "c2",
             "toolName": "bash",
             "args": {"command": "rm -rf ./build 2>/dev/null"}})
        out({"type": "extension_ui_request", "id": "uuid-1", "method": "select",
             "title": "Allow dangerous command?",
             "message": "rm -rf ./build",
             "options": ["Allow once", "Allow for session", "Deny"]})
        return                      # blocks until the client answers
    finish()

def finish():
    out({"type": "message_end", "message": {
        "role": "assistant",
        "content": [{"type": "text",
                     "text": "Looking at **that** now.\n\nHere is `code`:\n"
                             "```py\nx = 5 < 6\n```\n"}],
        "usage": {"input": 12000, "output": 240, "cacheRead": 0,
                  "cacheWrite": 0, "reasoning": 30, "totalTokens": 12270,
                  "cost": {"total": 0}}}})
    out({"type": "agent_end", "messages": [], "willRetry": False})
    out({"type": "agent_settled"})

MESSAGES = [
    {"role": "user", "content": "primer encargo de la sesion",
     "timestamp": 1756000000000},
    {"role": "assistant", "timestamp": 1756000001000, "content": [
        {"type": "thinking", "thinking": "razonamiento guardado"},
        {"type": "text", "text": "Miro el fichero."},
        {"type": "toolCall", "id": "h1", "name": "read_file",
         "arguments": {"path": "app/build.gradle"}}]},
    {"role": "assistant", "timestamp": 1756000001500, "content": [
        {"type": "toolCall", "id": "h2", "name": "edit", "arguments": {
            "path": "app/main.py", "edits": [
                {"oldText": "def run():\n    print('viejo')\n    return 1",
                 "newText": "def run():\n    print('nuevo')\n"
                            "    log('ok')\n    return 0"}]}}]},
    {"role": "toolResult", "toolCallId": "h2", "toolName": "edit",
     "isError": False, "timestamp": 1756000001800,
     "content": [{"type": "text", "text": "1 edit applied"}]},
    {"role": "toolResult", "toolCallId": "h1", "toolName": "read_file",
     "isError": False, "timestamp": 1756000002000,
     "content": [{"type": "text", "text": "plugins { id 'com.android...' }"}]},
    {"role": "assistant", "timestamp": 1756000003000, "content": [
        {"type": "text", "text": "Listo, **ya esta**."}]},
    # un comando que se corto: la llamada nunca recibio resultado y el turno
    # siguio. En historial debe salir stale (no "running", no parpadeo).
    {"role": "assistant", "timestamp": 1756000003500, "content": [
        {"type": "toolCall", "id": "cortado", "name": "bash",
         "arguments": {"command": "sleep 999"}}]},
    {"role": "user", "content": [{"type": "text", "text": "segundo encargo"}],
     "timestamp": 1756000004000},
    {"role": "toolResult", "toolCallId": "huerfano", "toolName": "bash",
     "isError": True, "timestamp": 1756000005000,
     "content": [{"type": "text", "text": "exit 1"}]},
    # mensaje enviado con sugerencias activas: pi guarda el prompt entero,
    # asi que la instruccion viaja pegada. La burbuja debe salir limpia.
    {"role": "user", "timestamp": 1756000006000, "content": [{"type": "text",
     "text": "tercer encargo\n\n[Reply normally to the message above. Then, "
             "on a new final line, output exactly: <hint: R> where R is a "
             "short, natural message the user might send next, in the user's "
             "language. Put nothing after it. If nothing fits, omit the "
             "line.]"}]},
    # mismo caso con el formato nuevo (tres hints, orden tajante)
    {"role": "user", "timestamp": 1756000007000, "content": [{"type": "text",
     "text": "cuarto encargo\n\n[After your reply, always end with exactly "
             "three suggestion lines: three short, natural messages the user "
             "might send next, in the user's language, each on its own final "
             "line in exactly this form:\n<hint: Sounds good, go ahead.>\n"
             "<hint: Wait, show me the diff first.>\n<hint: What about the "
             "tests?>\nReplace the example text with suggestions that fit. "
             "Always write all three lines. Write nothing after the third.]"}]},
    # el prompt inyectado del resumen-al-parar: pi lo guarda como mensaje de
    # usuario, pero NO lo escribio el usuario -> no debe salir en el transcripto.
    {"role": "user", "timestamp": 1756000008000, "content": [{"type": "text",
     "text": "You were just interrupted by the user. Reply with a single "
             "short line of plain text, in the user's language."}]},
    {"role": "assistant", "timestamp": 1756000008500, "content": [
        {"type": "text", "text": "Parado. Estaba mirando el build."}]},
]

TOKENS = 9000

MODELS = [
    {"id": "qwen3-8b", "name": "Qwen3 8B", "provider": "local",
     "contextWindow": 32768},
    {"id": "swift-27b", "name": "swift-27b", "provider": "swift",
     "contextWindow": 150000},
    {"id": "ornith15", "name": "ornith15", "provider": "ornith",
     "contextWindow": 132000},
]

STATE = {"model": MODELS[0],
         "thinkingLevel": "medium", "isStreaming": False,
         "sessionName": "fake session", "sessionId": "abc123",
         "sessionFile": "/tmp/fake.jsonl", "messageCount": 4}

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    cmd = json.loads(line)
    t = cmd.get("type")
    if t == "prompt":
        ABORT.clear()
        nimg = len(cmd.get("images") or [])
        threading.Thread(target=turn, args=(cmd.get("message", ""), nimg),
                         daemon=True).start()
    elif t == "extension_ui_response":
        out({"type": "response", "command": "ui", "success": True})
        threading.Thread(target=finish, daemon=True).start()
    elif t == "get_state":
        out({"type": "response", "command": "get_state", "success": True,
             "data": STATE})
    elif t == "get_session_stats":
        out({"type": "response", "command": "get_session_stats",
             "success": True,
             "data": {"cost": 0.0, "tokens": {"total": TOKENS},
                      "contextUsage": {"tokens": TOKENS,
                                       "contextWindow": 32768,
                                       "percent": round(100.0 * TOKENS / 32768,
                                                        2)}}})
    elif t == "get_messages":
        out({"type": "response", "command": "get_messages", "success": True,
             "data": {"messages": MESSAGES}})
    elif t == "get_available_models":
        out({"type": "response", "command": "get_available_models",
             "success": True, "data": {"models": MODELS}})
    elif t == "set_model":
        found = next((m for m in MODELS if m["provider"] == cmd.get("provider")
                      and m["id"] == cmd.get("modelId")), None)
        if found:
            STATE["model"] = found
            out({"type": "response", "command": "set_model",
                 "success": True, "data": found})
        else:
            out({"type": "response", "command": "set_model", "success": False,
                 "error": "Model not found: %s/%s"
                          % (cmd.get("provider"), cmd.get("modelId"))})
    elif t == "set_session_name":
        STATE["sessionName"] = cmd.get("name")
        out({"type": "response", "command": "set_session_name",
             "success": True})
    elif t == "new_session":
        # una sesion nueva nace sin nombre (el puente la autonombra o no)
        STATE["sessionName"] = None
        out({"type": "response", "command": "new_session", "success": True,
             "data": {}})
    elif t == "abort":
        ABORT.set()
        out({"type": "response", "command": "abort", "success": True})
    elif t == "fork":
        out({"type": "response", "command": "fork", "success": True,
             "data": {"cancelled": False, "text": "forked here"}})
    elif t == "get_fork_messages":
        out({"type": "response", "command": "get_fork_messages",
             "success": True, "data": {"messages": [
                 {"entryId": "e1", "text": "first question"},
                 {"entryId": "e2", "text": "do the thing\n\n[After your reply, "
                  "always end with exactly three suggestion lines: "
                  "<hint: a>\n<hint: b>\n<hint: c>]"},
                 {"entryId": "e3", "text": "You were just interrupted by the "
                  "user. Reply with a single short line of what you were doing."},
             ]}})
    else:
        out({"type": "response", "command": t, "success": True, "data": {}})
