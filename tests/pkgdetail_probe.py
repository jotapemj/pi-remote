"""Detalle de paquete del Store. El skeleton brilla con UNA onda alineada en
todas las barras (antes el color-mix de un solo color invalidaba el
degradado y no pintaba nada; y cada barra barria a su ritmo). Y los enlaces
del pie llevan el logo de su sitio: npm, GitHub, GitLab..., globo si no.
"""
import asyncio

from harness import Bridge, Page, report

SKEL = """(() => {
  openModal('x', storeDetailSkeleton('@a/b', false), () => {}, {});
  $('#modal').classList.add('pd'); skelSync($('#modalBody'));
})()"""

# se fija el instante con la Web Animations API: cambiar el retardo de una
# animacion ya en marcha suma el tiempo transcurrido y la medida miente
BANDS = """((t) => {
  const A = document.getAnimations().filter(a => a.animationName === 'skw');
  A.forEach(a => { a.pause(); a.currentTime = t; });
  // cada barra ve la caja comun en el mismo sitio: x + sx igual en todas,
  // y + sy = 0 (la diagonal sigue continua de barra en barra)
  const box = document.querySelector('.pdskel');
  const b0 = box.querySelector('.skel');
  const v = (b, k) => parseFloat(b.style.getPropertyValue(k));
  const bars = [...box.querySelectorAll('.skel')].map(b => {
    const cs = getComputedStyle(b, '::after');
    return [Math.round(parseFloat(cs.backgroundPositionX) + v(b, '--sx')),
            Math.round(parseFloat(cs.backgroundPositionY) + v(b, '--sy'))];
  });
  const xs = bars.map(b => b[0]), ys = bars.map(b => b[1]);
  return {n: A.length, bars: bars.length, min: Math.min(...xs),
          max: Math.max(...xs), yoff: Math.max(...ys.map(Math.abs)),
          img: getComputedStyle(b0, '::after').backgroundImage};
})"""

LINKS = """(() => {
  closeModal();
  const icon = (k, u) => ICONS[linkIcon(k, u)].slice(0, 10);
  return {
    npm: icon('npm', 'https://www.npmjs.com/package/x') === ICONS.brandNpm.slice(0, 10),
    gh: icon('repo', 'https://github.com/a/b') === ICONS.brandGithub.slice(0, 10),
    gl: icon('repo', 'https://gitlab.com/a/b') === ICONS.brandGitlab.slice(0, 10),
    cb: icon('repo', 'https://codeberg.org/a/b') === ICONS.brandCodeberg.slice(0, 10),
    ghHome: icon('home', 'https://github.com/a/b#readme') === ICONS.brandGithub.slice(0, 10),
    web: icon('home', 'https://example.dev') === ICONS.public.slice(0, 10),
    bad: icon('home', 'no es url') === ICONS.public.slice(0, 10),
    fake: icon('repo', 'https://github.com.evil.dev/x') === ICONS.public.slice(0, 10),
    drawn: (showStoreDetail({name: 'p', links: {npm: 'https://www.npmjs.com/package/p',
      repo: 'https://github.com/a/p', home: 'https://p.dev'}}),
      [...document.querySelectorAll('#modalBody .pdlinks a svg path')].length)};
})()"""


async def main():
    checks = []
    with Bridge():
        async with Page() as p:
            await p.go()
            await asyncio.sleep(0.8)
            await p.js(SKEL)
            await asyncio.sleep(0.5)
            a = await p.js(BANDS + "(600)")
            b = await p.js(BANDS + "(1000)")
            print("  ", {k: v for k, v in a.items() if k != "img"}, b["min"])
            checks += [
                ("el brillo pinta (degradado valido)",
                 a["img"].startswith("linear-gradient")),
                ("cada barra anima", a["n"] == a["bars"] > 10),
                ("una sola onda: todas ven el fondo comun en el mismo sitio",
                 a["max"] - a["min"] <= 1 and a["yoff"] <= 1),
                ("inclinada", "110deg" in a["img"]),
                ("y avanza de izquierda a derecha", b["min"] > a["min"]),
            ]
            ln = await p.js(LINKS)
            print("  ", ln)
            checks += [
                ("npm, GitHub, GitLab y Codeberg con su logo",
                 ln["npm"] and ln["gh"] and ln["gl"] and ln["cb"]),
                ("la web del paquete en GitHub lleva el de GitHub", ln["ghHome"]),
                ("una web cualquiera, o una url rota, el globo",
                 ln["web"] and ln["bad"]),
                ("un dominio que solo empieza igual no engana", ln["fake"]),
                ("los tres enlaces pintan su icono", ln["drawn"] == 3),
            ]
            # buscar en pi.dev: Enter aparta el teclado (quita el foco)
            await p.js("closeModal(); menuSheet(); goPage('store')")
            await asyncio.sleep(0.6)
            kb = await p.js("""(() => {
              const i = document.querySelector('#sheetBody .storeq input');
              i.focus(); const had = document.activeElement === i;
              i.dispatchEvent(new KeyboardEvent('keydown',
                {key: 'Enter', bubbles: true, cancelable: true}));
              return {had, gone: document.activeElement !== i,
                      hint: i.getAttribute('enterkeyhint')}; })()""")
            print("  ", kb)
            checks += [
                ("Enter en la busqueda aparta el teclado",
                 kb["had"] and kb["gone"]),
                ("la tecla del teclado movil dice buscar",
                 kb["hint"] == "search"),
            ]
    return checks


raise SystemExit(report(asyncio.run(main())))
