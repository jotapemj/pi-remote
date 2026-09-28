"""Nada del chat desplaza la pagina en horizontal. Una nota con una ruta
larga sin espacios (el aviso de guardrails) y un razonamiento que escribe
codigo ensanchaban el feed: en el movil se podia arrastrar de lado. Se mide
el desborde real (scrollWidth) de main, de la nota y del razonamiento.
"""
import asyncio

from harness import Bridge, Page, report

LONG = "C:/Users/me/Desktop/Android_Studio_Projects/Fision/app/src/main/java/" \
       "com/example/fision/PlayerActivity.java"

SETUP = r"""(() => {
  const id = 900000;
  render({id, kind:'note', level:'warn',
          text:'edit "%s" repeats %s blocked'});
  render({id: id+1, kind:'thinking', text:
    'Voy a mirar esto:\n\n```java\nfinal String p = "%s" + "%s";\n```\n\n'
    + 'y la ruta %s%s'});
  const th = [...feed.querySelectorAll('.think')].pop();
  if(th) th.open = true;
})()"""  % (LONG, LONG, LONG, LONG, LONG, LONG)

MEASURE = """(async () => {
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  main.scrollLeft = 400;
  const nt = [...feed.querySelectorAll('.note')].pop();
  const th = [...feed.querySelectorAll('.think')].pop();
  const pre = th && th.querySelector('pre');
  return {mainOver: main.scrollWidth - main.clientWidth,
          mainLeft: main.scrollLeft,
          feedOver: feed.scrollWidth - feed.clientWidth,
          noteW: nt.getBoundingClientRect().width, mainW: main.clientWidth,
          thinkW: th ? th.getBoundingClientRect().width : -1,
          pre: !!pre, preScroll: pre ? pre.scrollWidth > pre.clientWidth : null,
          preOx: pre ? getComputedStyle(pre).overflowX : null};
})()"""


async def main():
    checks = []
    with Bridge():
        async with Page() as p:
            await p.go()
            await asyncio.sleep(0.8)
            await p.js(SETUP)
            await asyncio.sleep(0.3)
            m = await p.js(MEASURE)
            print("  ", m)
            checks += [
                ("main no scrollea en horizontal", m["mainOver"] <= 0 and m["mainLeft"] == 0),
                ("el feed no desborda", m["feedOver"] <= 0),
                ("la nota cabe en el chat", m["noteW"] <= m["mainW"]),
                ("el razonamiento cabe en el chat", 0 < m["thinkW"] <= m["mainW"]),
                ("el codigo del razonamiento va en bloque", m["pre"]),
                ("con scroll propio", m["preOx"] == "auto" and m["preScroll"]),
            ]
    return checks

raise SystemExit(report(asyncio.run(main())))
