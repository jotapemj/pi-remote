"""Fundidos de borde de las listas (edgeFade): solo se funde el borde que
esconde algo. Arriba del todo no hay fundido arriba; al fondo no hay abajo;
sin desborde, ninguno. Se mide la clase y la mascara que de verdad pinta
(el tramo transparente del degradado), no solo que exista la regla.
"""
import asyncio

from harness import Bridge, Page, report

# mascara computada -> tamanos del fundido de arriba y de abajo en px
MASK = """(el => {
  const m = getComputedStyle(el).maskImage
    || getComputedStyle(el).webkitMaskImage || '';
  const px = [...m.matchAll(/(-?[\\d.]+)px/g)].map(x => +x[1]);
  return {t: el.classList.contains('fade-t'),
          b: el.classList.contains('fade-b'), m};
})"""

# llena la lista, mide en reposo, a media y al fondo, y vacia
SWEEP = """(async (sel, fill) => {
  const el = document.querySelector(sel);
  const probe = %s;
  const wait = () => new Promise(r => requestAnimationFrame(
    () => requestAnimationFrame(r)));
  const keep = el.innerHTML;
  el.style.scrollBehavior = 'auto';   // main scrollea suave: medir ya
  el.innerHTML = '';
  await wait();
  const empty = probe(el);
  el.innerHTML = fill;
  el.scrollTop = 0; await wait();
  const top = probe(el);
  el.scrollTop = (el.scrollHeight - el.clientHeight) / 2; await wait();
  const mid = probe(el);
  el.scrollTop = el.scrollHeight; await wait();
  const bot = probe(el);
  el.innerHTML = keep;
  el.style.scrollBehavior = '';
  return {empty, top, mid, bot};
})""" % MASK

ROWS = "".join('<div style="height:48px">fila %d</div>' % i for i in range(60))


def ok(r):
    return (not r["empty"]["t"] and not r["empty"]["b"]
            and not r["top"]["t"] and r["top"]["b"]
            and r["mid"]["t"] and r["mid"]["b"]
            and r["bot"]["t"] and not r["bot"]["b"])


async def main():
    checks = []
    with Bridge():
        async with Page(port=9422) as p:
            js = p.js
            await p.cmd("Emulation.setDeviceMetricsOverride", width=412,
                        height=860, deviceScaleFactor=1, mobile=True)
            await p.go()
            await asyncio.sleep(0.8)

            async def sweep(sel):
                return await js("%s(%r, %r)" % (SWEEP, sel, ROWS))

            # papelera y buscar chats: sus vistas abiertas
            await js("openTrash()")
            await asyncio.sleep(0.6)
            tr = await sweep("#trashList")
            await js("closeTrash ? closeTrash() : 0")
            await js("openSearch()")
            await asyncio.sleep(0.6)
            se = await sweep("#searchList")
            await js("closeSearch()")
            await asyncio.sleep(0.4)
            # hojas
            await js("menuSheet()")
            await asyncio.sleep(0.6)
            sh = await sweep("#sheetBody")
            await js("$('#sheet').classList.remove('open')")
            # chat
            ch = await sweep("main")
            for n, r in (("papelera", tr), ("buscar", se), ("hoja", sh),
                         ("chat", ch)):
                print("  %-9s reposo=%s/%s media=%s/%s fondo=%s/%s vacia=%s/%s"
                      % (n, r["top"]["t"], r["top"]["b"], r["mid"]["t"],
                         r["mid"]["b"], r["bot"]["t"], r["bot"]["b"],
                         r["empty"]["t"], r["empty"]["b"]))
            checks += [
                ("papelera: fundido solo en el borde que esconde algo", ok(tr)),
                ("buscar chats: igual", ok(se)),
                ("hojas: igual", ok(sh)),
                ("chat: igual", ok(ch)),
            ]

            # la mascara pinta de verdad: arriba del todo, el tramo
            # transparente de arriba mide 0; a media lista, el de la papelera
            # mide sus 22 px
            await js("openTrash()")
            await asyncio.sleep(0.6)
            m = await js("""(async () => {
              const el = $('#trashList'); const keep = el.innerHTML;
              el.innerHTML = %r;
              const wait = () => new Promise(r => requestAnimationFrame(
                () => requestAnimationFrame(r)));
              el.scrollTop = 0; await wait();
              const a = getComputedStyle(el).maskImage;
              el.scrollTop = 400; await wait();
              const b = getComputedStyle(el).maskImage;
              el.innerHTML = keep; return [a, b];})()""" % ROWS)
            print("  mascara reposo: %s" % m[0][:90])
            print("  mascara media : %s" % m[1][:90])
            checks += [
                ("en reposo la mascara no funde arriba",
                 "rgb(0, 0, 0) 0px" in m[0]),
                ("a media lista funde 22 px arriba",
                 "rgb(0, 0, 0) 22px" in m[1]),
            ]

            # hoja: el fundido de arriba es un overlay sticky (una mascara
            # fundiria las cabeceras sticky): pinta solo con .fade-t
            await js("menuSheet()")
            await asyncio.sleep(0.6)
            ov = await js("""(async () => {
              const el = $('#sheetBody'); const keep = el.innerHTML;
              el.innerHTML = %r;
              const wait = () => new Promise(r => requestAnimationFrame(
                () => requestAnimationFrame(r)));
              el.scrollTop = 0; await wait();
              const a = getComputedStyle(el, '::before').backgroundImage;
              el.scrollTop = 400; await wait();
              const b = getComputedStyle(el, '::before').backgroundImage;
              el.innerHTML = keep; return [a, b];})()""" % ROWS)
            checks.append(("hoja: el overlay de arriba solo pinta al bajar",
                           ov[0] == "none" and "gradient" in ov[1]))

            # secciones con cabecera sticky (Recursos): la cabecera tapa el
            # overlay de la hoja, asi que el fundido va bajo la pegada, y
            # solo bajo esa; en reposo ninguna funde
            await js("goPage('resglobal')")
            await asyncio.sleep(0.8)
            await js("""onRpc({type:'rpc', command:'skills_list', data:{
              scope:'global', skills: Array.from({length:14}, (_, i) => ({
                dir:'s'+i, name:'skill-'+i, description:'d', enabled:true,
                files:1}))}});
              onRpc({type:'rpc', command:'extensions_list', data:{
                scope:'global', extensions:[{name:'e', path:'x'}]}});""")
            await asyncio.sleep(0.5)
            st = await js("""(async () => {
              const el = $('#sheetBody');
              const wait = () => new Promise(r => requestAnimationFrame(
                () => requestAnimationFrame(r)));
              const heads = () => [...el.querySelectorAll('.sec > .shead')]
                .map(h => [h.textContent, h.classList.contains('stuck'),
                  +getComputedStyle(h, '::after').opacity]);
              el.scrollTop = 0; await wait();
              const a = heads();
              el.scrollTop = 300; await wait();
              const b = heads();
              return [a, b];})()""")
            print("  cabeceras reposo=%s  bajado=%s" % tuple(st))
            checks += [
                ("seccion: en reposo ninguna cabecera funde",
                 not any(h[1] or h[2] > 0 for h in st[0])),
                ("bajado: funde solo bajo la cabecera pegada",
                 st[1][0][1] and st[1][0][2] == 1
                 and not any(h[1] for h in st[1][1:])),
            ]
            await js("$('#sheet').classList.remove('open')")

            # buscar conversaciones es una hoja: lleva su pill, como la papelera
            gb = await js("""[!!document.querySelector('#searchView > .grab'),
              !!document.querySelector('#trashView > .grab')]""")
            checks.append(("buscar y papelera llevan la pill de hoja",
                           gb == [True, True]))

            # rail: el fundido del pie solo con filas escondidas debajo
            rl = await js("""(async () => {
              const el = document.querySelector('.railscroll');
              const keep = el.innerHTML;
              const wait = () => new Promise(r => requestAnimationFrame(
                () => requestAnimationFrame(r)));
              const foot = () => +getComputedStyle(
                document.querySelector('.railfoot'), '::before').opacity;
              $('#rail').classList.add('open');
              el.innerHTML = %r; el.scrollTop = 0; await wait();
              await new Promise(r => setTimeout(r, 250));
              const a = foot();
              el.scrollTop = el.scrollHeight; await wait();
              await new Promise(r => setTimeout(r, 250));
              const b = foot();
              el.innerHTML = keep; return [a, b];})()""" % ROWS)
            print("  pie del rail: con filas debajo=%s al fondo=%s" % tuple(rl))
            checks.append(("rail: el fundido del pie solo con filas debajo",
                           rl[0] > 0.9 and rl[1] < 0.1))
    return checks


raise SystemExit(report(asyncio.run(main())))
