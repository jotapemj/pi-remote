"""Separador de tiempo: al volver tras un paron, una onda con la fecha antes
del mensaje del usuario. Paron = 3 h desde el ultimo item de conversacion, o
cambio de dia con al menos 30 min. Las notas no cuentan como hablar. Se mide
el feed vivo, el snapshot (historial), el envio deshecho y la forma pintada:
la onda se corta en el texto (nada detras) y se aprieta hacia el centro.
"""
import asyncio
import json
import os

from harness import Bridge, Page, report

SHOT = os.environ.get("PI_SHOT")     # ruta opcional para ver la captura
H, M = 3600e3, 60e3

# base: hace tres dias a las 12:00 locales (el "cambio de dia" no depende
# de la hora de la pasada)
BASE = """(() => { const D = new Date(); D.setHours(12, 0, 0, 0);
  return D.getTime() - 3 * 864e5; })()"""

# lo que llega del puente: un snapshot con los items
SNAP = """((items) => {
  ws.onmessage({data: JSON.stringify({type: 'snapshot', items,
    state: Object.assign({}, state), cwd: CWD})});
  return [...feed.children].map(e => e.classList.contains('tsep')
    ? 'SEP:' + e.querySelector('span').textContent
    : e.__item.kind + ':' + e.__item.text);
})"""


def items(base):
    return [
        {"id": 1, "kind": "user", "text": "u1", "t": base},
        {"id": 2, "kind": "assistant", "text": "a1", "t": base + 5 * M},
        # 2 h 59 despues de a1: seguida, sin linea
        {"id": 3, "kind": "user", "text": "u2", "t": base + 184 * M},
        {"id": 4, "kind": "assistant", "text": "a2", "t": base + 185 * M},
        # una nota 4 h despues no es hablar: el paron se mide desde a2
        {"id": 5, "kind": "note", "text": "n", "t": base + 185 * M + 4 * H},
        # 3 h justas desde a2: linea
        {"id": 6, "kind": "user", "text": "u3", "t": base + 185 * M + 3 * H},
        # a3 a las 23:40; u4 a las 00:15 del dia siguiente (35 min): linea
        {"id": 7, "kind": "assistant", "text": "a3", "t": base + 11 * H + 40 * M},
        {"id": 8, "kind": "user", "text": "u4", "t": base + 12 * H + 15 * M},
        {"id": 9, "kind": "assistant", "text": "a4", "t": base + 12 * H + 16 * M},
        # 00:16 -> 00:30, mismo dia y 14 min: nada
        {"id": 10, "kind": "user", "text": "u5", "t": base + 12 * H + 30 * M},
    ]


async def main():
    checks = []
    with Bridge():
        async with Page() as p:
            await p.go()
            await asyncio.sleep(0.8)
            await p.js("setLang('es')")
            base = await p.js(BASE)
            seq = await p.js(SNAP + "(%s)" % json.dumps(items(base)))
            print("  ", seq)
            before = [seq[i + 1] for i, x in enumerate(seq)
                      if x.startswith("SEP:")]
            order = [x.split(":")[1] for x in seq if not x.startswith("SEP:")]
            checks += [
                ("dos lineas: tras 3 h y tras medianoche con 35 min",
                 before == ["user:u3", "user:u4"]),
                ("a 2 h 59 no hay linea, ni a 14 min el mismo dia",
                 "user:u2" not in before and "user:u5" not in before),
                ("las notas no cuentan como conversacion",
                 "user:u3" in before),
                ("el orden de los mensajes no cambia", order
                 == ["u1", "a1", "u2", "a2", "n", "u3", "a3", "u4", "a4", "u5"]),
            ]
            lab = await p.js("""(() => {
              const D = new Date(); D.setHours(9, 5, 0, 0);
              const r = {today: sepLabel(D.getTime()),
                         yday: sepLabel(D.getTime() - 864e5),
                         old: sepLabel(new Date(2024, 8, 22, 9, 15).getTime())};
              setLang('en'); r.en = sepLabel(D.getTime()); setLang('es');
              return r; })()""")
            print("  ", lab)
            checks += [
                ("hoy con hora", lab["today"] == "Hoy 09:05"),
                ("ayer con hora", lab["yday"] == "Ayer 09:05"),
                ("otro anyo: fecha con anyo",
                 "2024" in lab["old"] and "22" in lab["old"]),
                ("en ingles tambien, sin cadenas propias",
                 lab["en"] == "Today 09:05"),
            ]
            # forma pintada: dos mitades a los lados del texto, sin solaparse
            geo = await p.js("""(() => {
              const s = feed.querySelector('.tsep');
              const [l, r] = s.querySelectorAll('svg'),
                    t = s.querySelector('span');
              const L = l.getBoundingClientRect(), R = r.getBoundingClientRect(),
                    T = t.getBoundingClientRect(), F = feed.getBoundingClientRect();
              return {gapL: T.left - L.right, gapR: R.left - T.right,
                      center: Math.abs((T.left + T.right) / 2
                                       - (F.left + F.right) / 2),
                      mirror: getComputedStyle(r).transform,
                      wide: L.width > 60 && R.width > 60}; })()""")
            print("  ", geo)
            checks += [
                ("la onda se corta en el texto: nada detras",
                 geo["gapL"] > 0 and geo["gapR"] > 0),
                ("la fecha en el centro", geo["center"] < 2),
                ("la mitad derecha es la izquierda espejada",
                 geo["mirror"].startswith("matrix(-1")),
                ("las dos mitades llenan el ancho", geo["wide"]),
            ]
            # la onda: periodo en pixeles reales, 10 px fuera y algo mas
            # apretada (7 px) junto a la fecha; igual en cualquier ancho
            zc = await p.js("""(() => {
              const pts = W => sepPath(W).slice(1).split('L')
                .map(q => q.split(' ').map(Number));
              const cross = (P, a, b) => P.filter((q, i) => i && q[0] >= a
                && q[0] < b && (P[i-1][1] - 4) * (q[1] - 4) < 0).length;
              const P = pts(300), S = pts(150), B = pts(400);
              const v = feed.querySelector('.tsep svg');
              return {outer: cross(P, 0, 90), inner: cross(P, 210, 300),
                      edgeS: cross(S, 0, 40), edgeB: cross(B, 0, 40),
                      endY: P[P.length - 1][1],
                      drawn: (v.firstChild.getAttribute('d') || '').length,
                      vb: v.getAttribute('viewBox'),
                      w: Math.round(v.getBoundingClientRect().width)}; })()""")
            print("  ", zc)
            checks += [
                ("la frecuencia sube hacia la fecha, solo un poco",
                 1.1 < zc["inner"] / zc["outer"] < 1.6),
                ("el borde tiene el mismo periodo en cualquier ancho",
                 abs(zc["edgeS"] - zc["edgeB"]) <= 1),
                ("llega al corte en el eje", abs(zc["endY"] - 4) < 0.05),
                ("pintada a su ancho real", zc["drawn"] > 100
                 and zc["vb"] == "0 0 %d 8" % zc["w"]),
            ]
            if SHOT:
                await p.js("main.style.scrollBehavior='auto'; main.scrollTop = 0")
                await asyncio.sleep(0.4)
                await p.shot(SHOT)
            # en vivo: un envio tras el paron trae su linea; deshecho, se va
            drop = await p.js("""(() => {
              const n = () => feed.querySelectorAll('.tsep').length;
              const a = n();
              ws.onmessage({data: JSON.stringify({type: 'item', item:
                {id: 99, kind: 'user', text: 'x', t: Date.now()}})});
              const b = n();
              ws.onmessage({data: JSON.stringify({type: 'drop', id: 99})});
              return [a, b, n()]; })()""")
            print("  ", drop)
            checks += [
                ("en vivo, el mensaje tras el paron trae linea",
                 drop[1] == drop[0] + 1),
                ("deshacer el envio quita su linea", drop[2] == drop[0]),
            ]
    return checks

raise SystemExit(report(asyncio.run(main())))
