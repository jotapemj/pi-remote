# -*- coding: utf-8 -*-
"""Compactar: la card dice 'compactando' y esa misma se resuelve, y la
barra sube en vivo con el prefill. Contra fake_pi, sin agente real."""
import asyncio
import json
from harness import Bridge, FakeProject, Page, report

LAST = ("(() => { const n = [...document.querySelectorAll('.note')].pop();"
        " return n ? [n.querySelector('span').textContent,"
        "  n.classList.contains('busy'),"
        "  document.querySelectorAll('.note').length,"
        "  n.dataset.k || (n.__x=1)] : null; })()")


async def wait_for(js, needle, secs=6):
    end = asyncio.get_event_loop().time() + secs
    while asyncio.get_event_loop().time() < end:
        v = await js("(() => { const n ="
                     " [...document.querySelectorAll('.note')].find(x =>"
                     " x.querySelector('span').textContent.toLowerCase()"
                     ".includes(%r)); return n ?"
                     " [n.querySelector('span').textContent,"
                     "  n.classList.contains('busy'),"
                     "  document.querySelectorAll('.note').length] : null;"
                     "})()" % needle)
        if v:
            return v
        await asyncio.sleep(0.1)
    return None


async def main():
    checks = []
    with Bridge(), FakeProject() as proj:
        async with Page(port=9314) as p:
            js = p.js
            await p.go()
            await js("setLang('es')")
            await js("send({type:'open_project', path:%s})"
                     % json.dumps(proj.path))
            await asyncio.sleep(1.6)
            base = await js("document.querySelectorAll('.note').length")

            await js("send({type:'prompt', message:'compact ahora'})")
            busy = await wait_for(js, "comprimiendo")
            print("  compactando: %r  (habia %d notas)" % (busy, base))
            done = await wait_for(js, "comprimido")
            print("  resuelta   : %r" % (done,))

            bar0 = await js("$('#bar').firstElementChild.style.width")
            await asyncio.sleep(4.2)
            bar1 = await js("$('#bar').firstElementChild.style.width")
            lbl = await js("$('#bar').lastElementChild.textContent")
            print("  barra: %s -> %s  (%r)" % (bar0, bar1, lbl))

            def pctof(w):
                try: return float(w.replace("%", ""))
                except: return -1

            checks += [
                ("mientras compacta, una nota que lo dice y late",
                 busy is not None and busy[1] is True
                 and busy[2] == base + 1),
                ("esa misma nota se resuelve, sin duplicar",
                 done is not None and done[2] == base + 1
                 and done[1] is False),
                ("la barra sube en vivo con el prefill, sin generar",
                 pctof(bar1) > pctof(bar0) + 2),
            ]
    return checks


if __name__ == "__main__":
    report(asyncio.run(main()))
