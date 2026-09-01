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

def turn(text):
    out({"type": "agent_start"})
    out({"type": "message_start", "message": {"role": "assistant", "content": []}})
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
                             "```py\nx = 5 < 6\n```\n"}]}})
    out({"type": "agent_end", "messages": [], "willRetry": False})
    out({"type": "agent_settled"})

MESSAGES = [
    {"role": "user", "content": "primer encargo de la sesion",
     "timestamp": 1756000000000},
    {"role": "assistant", "timestamp": 1756000001000, "content": [
        {"type": "thinking", "thinking": "esto no debe salir"},
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
    {"role": "user", "content": [{"type": "text", "text": "segundo encargo"}],
     "timestamp": 1756000004000},
    {"role": "toolResult", "toolCallId": "huerfano", "toolName": "bash",
     "isError": True, "timestamp": 1756000005000,
     "content": [{"type": "text", "text": "exit 1"}]},
]

TOKENS = 9000

STATE = {"model": {"id": "qwen3-8b", "name": "Qwen3 8B", "provider": "local",
                   "contextWindow": 32768},
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
        threading.Thread(target=turn, args=(cmd.get("message", ""),),
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
             "success": True, "data": {"models": [STATE["model"]]}})
    elif t == "abort":
        out({"type": "response", "command": "abort", "success": True})
        out({"type": "agent_settled"})
    else:
        out({"type": "response", "command": t, "success": True, "data": {}})
