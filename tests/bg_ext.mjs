// La extension de tareas en segundo plano, ejecutada de verdad con Node
// (que ya quita los tipos de TypeScript) contra un `pi` falso: registra las
// herramientas, recoge los sendMessage y contesta los dialogos. Los comandos
// corren de verdad en el bash de pi. Escribe un JSON de comprobaciones que
// lee bg_probe.py. Sin modelo.
import { register } from "node:module";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { pathToFileURL } from "node:url";

const PI = process.env.PI_PKG;
// typebox lo trae pi: se resuelve desde su instalacion
register("data:text/javascript," + encodeURIComponent(`
  export async function resolve(spec, ctx, next) {
    if (spec === "typebox")
      return next(${JSON.stringify(pathToFileURL(path.join(PI, "node_modules", "typebox", "")).href)}
                  + "build/index.mjs", ctx).catch(() => next(spec, { ...ctx,
        parentURL: ${JSON.stringify(pathToFileURL(path.join(PI, "package.json")).href)} }));
    return next(spec, ctx);
  }`));

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "pi-bg-"));
const proj = path.join(tmp, "proj"), other = path.join(tmp, "other");
fs.mkdirSync(proj); fs.mkdirSync(other);
process.env.PI_REMOTE_JOBS = path.join(tmp, "jobs");
const cfg = path.join(tmp, "perm.json");
fs.writeFileSync(cfg, JSON.stringify({ permission: { "*": "allow" } }));
process.env.PI_REMOTE_PERMCFG = cfg;

const mod = await import(pathToFileURL(path.resolve("extensions/background.ts")).href);
const tools = {}, handlers = {}, sent = [];
const pi = {
  registerTool: (t) => (tools[t.name] = t),
  on: (ev, f) => (handlers[ev] ||= []).push(f),
  sendMessage: (m, o) => sent.push({ m, o }),
};
mod.default(pi);

let answer = "Allow once", asked = [];
const ctx = (over = {}) => ({
  cwd: proj, hasUI: true, mode: "rpc",
  ui: { select: async (title, opts) => { asked.push({ title, opts }); return answer; } },
  ...over,
});
const run = (name, params, c = ctx()) =>
  tools[name].execute("t", params, undefined, undefined, c);
const out = (r) => r.content[0].text;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const checks = [];
const ok = (name, cond, info) => { checks.push([name, !!cond]); if (!cond && info !== undefined) console.error(name, info); };

await handlers.session_start[0]({}, ctx());

ok("registra las cinco herramientas",
   ["bg_run", "bg_list", "bg_log", "bg_wait", "bg_kill"].every((n) => tools[n]));

// --- permiso
answer = "Deny"; asked = [];
let r = await run("bg_run", { command: "echo nunca" });
ok("sin permission-system pregunta, con el comando en el dialogo",
   asked.length === 1 && asked[0].title.includes("echo nunca")
   && asked[0].opts.length === 3, asked);
ok("denegar no lanza nada", out(r).startsWith("Denied") && mod.allJobs().length === 0);

r = await run("bg_run", { command: "echo x" }, ctx({ hasUI: false }));
ok("sin nadie a quien preguntar, deniega", out(r).startsWith("Denied") && mod.allJobs().length === 0);

answer = "Allow this command for this session"; asked = [];
r = await run("bg_run", { command: "echo uno; exit 7", label: "prueba" });
const id1 = r.details.id;
await run("bg_run", { command: "echo uno; exit 7" });
ok("permitir en la sesion: el mismo comando no vuelve a preguntar", asked.length === 1, asked);

fs.writeFileSync(cfg, JSON.stringify({ shellTools: { bg_run: { commandArgument: "command" } } }));
asked = [];
const rg = await run("bg_run", { command: "echo gated" });
ok("con shellTools.bg_run decide permission-system: no pregunta dos veces",
   asked.length === 0 && rg.details.id > 0);
fs.writeFileSync(cfg, JSON.stringify({ permission: {} }));

// --- resultado y codigo de salida
answer = "Allow once";
r = await run("bg_wait", { id: id1, seconds: 20 });
let j = mod.readJob(id1);
ok("un exit dentro del comando no se come el codigo (7)",
   j.status === "failed" && j.code === 7, j);
ok("bg_wait devuelve el estado y la salida", /failed \(exit code 7\)/.test(out(r)) && out(r).includes("uno"), out(r));

// --- barras de progreso y colores
r = await run("bg_run", { command: "printf 'cargando\\r50%%\\r100%%\\n\\033[31mrojo\\033[0m\\nwarning: ojo\\n'" });
await run("bg_wait", { id: r.details.id, seconds: 20 });
const lines = mod.tail(r.details.id, 10);
ok("la salida llega limpia: sin \\r de la barra ni colores",
   JSON.stringify(lines) === JSON.stringify(["100%", "rojo", "warning: ojo"]), lines);
r = await run("bg_log", { id: r.details.id, grep: "WARN" });
ok("bg_log filtra sin distinguir mayusculas", out(r).split("\n").slice(1).join("|") === "warning: ojo", out(r));

// --- aviso al terminar y despertar al agente
sent.length = 0;
r = await run("bg_run", { command: "sleep 1; echo hecho", label: "build" });
const idw = r.details.id;
const forW = () => sent.find((x) => x.m.details.id === idw);
for (let k = 0; k < 30 && !forW(); k++) await sleep(250);
const s0 = forW();
ok("al terminar avisa solo, con su salida",
   s0 && s0.m.customType === "pi-remote:bg" && s0.m.content.includes("#" + idw)
   && s0.m.content.includes("hecho") && s0.m.details.status === "done", s0);
ok("y despierta al agente al acabar su turno",
   s0 && s0.o.triggerTurn === true && s0.o.deliverAs === "followUp", s0 && s0.o);
await sleep(2500);
ok("avisa una sola vez", sent.filter((x) => x.m.details.id === idw).length === 1, sent.length);

// --- tope de despertares seguidos sin el usuario (contando desde cero)
await handlers.input[0]({}, ctx());
sent.length = 0;
for (let k = 0; k < 6; k++) {
  const rr = await run("bg_run", { command: "true" });
  await run("bg_wait", { id: rr.details.id, seconds: 10 });
  const jj = mod.readJob(rr.details.id); jj.notified = false; // que avise el sondeo
  fs.writeFileSync(path.join(process.env.PI_REMOTE_JOBS, rr.details.id + ".json"), JSON.stringify(jj));
  for (let t = 0; t < 20 && sent.length <= k; t++) await sleep(200);
}
const trig = sent.map((x) => !!x.o.triggerTurn);
ok("tras 5 despertares seguidos deja de despertar (avisa sin turno)",
   JSON.stringify(trig) === "[true,true,true,true,true,false]"
   && sent[5].o.deliverAs === "nextTurn", trig);
await handlers.input[0]({}, ctx());
sent.length = 0;
const rr = await run("bg_run", { command: "true" });
for (let t = 0; t < 20 && !sent.length; t++) await sleep(200);
ok("cuando el usuario escribe, vuelve a despertar", sent[0] && sent[0].o.triggerTurn === true, sent);

// --- tope de tareas y parar
const longs = [];
for (let k = 0; k < 3; k++) longs.push((await run("bg_run", { command: "sleep 30" })).details.id);
r = await run("bg_run", { command: "sleep 30" });
ok("como mucho 3 a la vez", out(r).startsWith("Error: 3 tasks"), out(r));
r = await run("bg_list", {});
ok("bg_list las enumera", longs.every((i) => out(r).includes("#" + i)) && out(r).includes("running"), out(r));
const pid = mod.readJob(longs[0]).pid;
sent.length = 0;
r = await run("bg_kill", { id: longs[0] });
await sleep(800);
let alive = true; try { process.kill(pid, 0); } catch { alive = false; }
ok("bg_kill para la tarea entera", out(r).startsWith("Stopped") && !alive
   && mod.readJob(longs[0]).status === "killed");
await sleep(2500);
ok("parada a proposito: no despierta al agente",
   !sent.some((x) => x.m.details.id === longs[0]), sent);
for (const i of longs.slice(1)) await run("bg_kill", { id: i });

// --- solo lo de este proyecto
const ro = await run("bg_run", { command: "echo ajena" }, ctx({ cwd: other }));
await sleep(300);
r = await run("bg_log", { id: ro.details.id });
ok("una tarea de otro proyecto no se ve ni se toca desde este",
   out(r).startsWith("Error: no task"), out(r));

// --- se retoma desde disco tras reiniciar pi
const rs = await run("bg_run", { command: "sleep 2; echo tras reinicio" });
await handlers.session_shutdown[0]({}, ctx());
const tools2 = {}, h2 = {}, sent2 = [];
mod.default({ registerTool: (t) => (tools2[t.name] = t), on: (e, f) => (h2[e] ||= []).push(f),
              sendMessage: (m, o) => sent2.push({ m, o }) });
await h2.session_start[0]({}, ctx());
for (let k = 0; k < 30 && !sent2.some((x) => x.m.details.id === rs.details.id); k++) await sleep(250);
ok("un pi nuevo retoma la tarea y avisa al terminar",
   sent2.some((x) => x.m.details.id === rs.details.id && x.m.content.includes("tras reinicio")), sent2);
await h2.session_shutdown[0]({}, ctx());

console.log(JSON.stringify(checks));
fs.rmSync(tmp, { recursive: true, force: true });
process.exit(0);
