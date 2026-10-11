"""Restart now: todo dialogo que avisa "aplica al reiniciar pi remote" ofrece
un tercer boton que guarda Y reinicia. Orden apilado: la accion principal
arriba, Restart now debajo, cancel al fondo. El guardado sale antes que el
restart por el mismo WebSocket; con el agente ocupado sale el dialogo de
/restart ocupado. Tambien el aviso tras instalar o quitar un paquete.
Los envios se interceptan: el puente real no se toca.
"""
import asyncio
import json
import re
from pathlib import Path

from harness import Bridge, Page, report

SRC = (Path(__file__).resolve().parent.parent / "static" / "index.html") \
    .read_text(encoding="utf-8")

SPY = """(() => {
  window.__sent = [];
  const s0 = ws.send.bind(ws);
  ws.send = x => { const o = JSON.parse(x);
    if(/^(instructions_|restart|store_)/.test(o.type)){
      window.__sent.push(o); return; }
    return s0(x); };
})()"""

FILES = [{"kind": "agents", "name": "AGENTS.md",
          "path": "C:/Users/me/.pi/agent/AGENTS.md", "exists": True,
          "body": "a"}]

BOX = """(() => {
  const r = id => { const e = $(id); return e.hidden ? null
                    : e.getBoundingClientRect().top; };
  return {open: $('#modal').classList.contains('open'),
          title: $('#modalTitle').textContent,
          extra: $('#modalExtra').hidden ? null : $('#modalExtra').textContent,
          ok: r('#modalOk'), ex: r('#modalExtra'), no: r('#modalNo')}; })()"""


def static():
    # los 9 dialogos de confirmacion que avisan del reinicio
    n = len(re.findall(r"restart: true\}", SRC))
    return [("los 9 dialogos 'aplica al reiniciar' llevan restart", n == 9)]


async def edit_and_save(js):
    await js("instrDraft = null; openInstr('global')")
    await asyncio.sleep(0.4)
    await js("onRpc({command:'instructions_get', data:{scope:'global',"
             " files:%s, also:[]}})" % json.dumps(FILES))
    await asyncio.sleep(0.3)
    await js("[...document.querySelectorAll('#sheetBody .pick')][0].click()")
    await asyncio.sleep(0.4)
    await js("""(() => { const t = document.querySelector('#sheetBody textarea');
      t.value = 'b'; t.dispatchEvent(new Event('input')); $('#sheetOk').click(); })()""")
    await asyncio.sleep(0.4)


async def ui():
    checks = []
    with Bridge():
        async with Page() as p:
            js = p.js
            await p.go()
            await asyncio.sleep(0.8)
            await js("setLang('en')")
            await js(SPY)
            await js("menuSheet()")
            await asyncio.sleep(0.3)

            # agente libre: guarda y reinicia, en ese orden
            await edit_and_save(js)
            b = await js(BOX)
            print("  dialogo:", b)
            await js("$('#modalExtra').click()")
            await asyncio.sleep(0.3)
            sent = await js("window.__sent.filter(o => o.type !== 'instructions_get')"
                            ".map(o => o.type)")
            print("  enviado:", sent)
            checks += [
                ("el dialogo de guardar ofrece Restart now",
                 b["open"] and b["extra"] == "Restart now"),
                ("orden: principal, Restart now, cancel",
                 None not in (b["ok"], b["ex"], b["no"])
                 and b["ok"] < b["ex"] < b["no"]),
                ("Restart now guarda y luego reinicia",
                 sent == ["instructions_save", "restart"]),
            ]
            await js("restartLock(false); window.__sent = []")

            # agente ocupado: guarda y sale el dialogo de /restart ocupado
            await js("state.running = true")
            await edit_and_save(js)
            await js("$('#modalExtra').click()")
            await asyncio.sleep(0.3)
            busy = await js(BOX)
            sent = await js("window.__sent.filter(o => o.type !== 'instructions_get')"
                            ".map(o => o.type)")
            checks += [
                ("ocupado: guarda y pregunta como /restart",
                 sent == ["instructions_save"]
                 and busy["open"] and busy["title"] == "The agent is busy"),
                ("y conserva su orden propio (Wait arriba)",
                 busy["extra"] == "Wait" and busy["ex"] < busy["ok"]),
            ]
            await js("closeModal(); state.running = false; window.__sent = []")

            # un dialogo sin reinicio no lleva el tercer boton
            await js("confirmModal('Q', '', () => {})")
            await asyncio.sleep(0.2)
            plain = await js(BOX)
            await js("closeModal()")
            checks.append(("un confirm normal no lleva Restart now",
                           plain["extra"] is None))

            # tras instalar un paquete del store
            await js("""storeBusyName = 'pkg';
              openModal('Install', '', () => {}, {ok: T('confirm')})""")
            await asyncio.sleep(0.2)
            await js("onRpc({command:'store_install', name:'pkg', data:{}})")
            await asyncio.sleep(0.2)
            st = await js(BOX)
            await js("$('#modalExtra').click()")
            await asyncio.sleep(0.3)
            sent = await js("window.__sent.map(o => o.type)")
            checks += [
                ("instalado: el aviso ofrece Restart now",
                 st["extra"] == "Restart now" and st["no"] is None
                 and st["ok"] < st["ex"]),
                ("y reinicia al pulsarlo", sent == ["restart"]),
            ]
    return checks


async def main():
    return static() + await ui()

raise SystemExit(report(asyncio.run(main())))
