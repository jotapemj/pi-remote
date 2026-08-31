const { JSDOM } = require("/tmp/node_modules/jsdom");
const fs = require("fs");

const html = fs.readFileSync("/home/claude/static/index.html", "utf8");
const js = html.match(/<script>\n([\s\S]*)\n<\/script>/)[1];

// stub the socket so the page loads without a server
class FakeWS {
  constructor(){ this.readyState = 1; this.sent = []; FakeWS.last = this; }
  send(s){ this.sent.push(JSON.parse(s)); }
  close(){}
}
// load the markup only, then run the script once with the stub in place
const dom = new JSDOM(html.replace(/<script>[\s\S]*<\/script>/, "<script></script>"),
                      { runScripts: "dangerously", url: "http://x/" });
dom.window.WebSocket = FakeWS;
dom.window.matchMedia = () => ({ matches: false });
dom.window.eval(js);

const w = dom.window, d = w.document;
const box = d.querySelector("#box");
const pal = d.querySelector("#palette");
const type = v => { box.value = v; box.dispatchEvent(new w.Event("input")); };
const key = k => {
  const e = new w.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true });
  box.dispatchEvent(e); return e;
};
const items = () => [...d.querySelectorAll(".cmd b")].map(x => x.textContent.trim());
const ok = (label, cond) => console.log((cond ? "PASS  " : "FAIL  ") + label);

// 1. nothing shown for ordinary text
type("hola que tal");
ok("hidden for plain text", pal.hidden === true);

// 2. slash opens the full list
type("/");
ok("slash opens palette", pal.hidden === false);
const all = items();
console.log("      commands:", all.length);
ok("21 commands listed", all.length === 21);

// 3. filtering
type("/st");
console.log("      /st ->", items().join(" "));
ok("filters to stats/state/steer", items().length === 3);

// 4. no match
type("/zzz");
ok("no-match message", d.querySelector(".palette .none") !== null);

// 5. arrow keys move the selection
type("/s");
const before = d.querySelector(".cmd.sel b").textContent.trim();
key("ArrowDown");
const after = d.querySelector(".cmd.sel b").textContent.trim();
ok("arrow moves selection", before !== after);
console.log("      " + before + " -> " + after);

// 6. Enter on a no-arg command sends it and clears the box
type("/stats");
key("Enter");
const sent = FakeWS.last.sent;
ok("enter runs command", sent.length && sent[sent.length-1].type === "get_session_stats");
ok("box cleared", box.value === "");
ok("palette closed", pal.hidden === true);

// 7. a command that needs an argument prefills instead of running
type("/bash");
key("Enter");
ok("arg command prefills", box.value === "/bash ");
ok("nothing sent yet", FakeWS.last.sent.length === sent.length);

// 8. space after the command name closes the palette (now typing an argument)
type("/bash git status");
ok("palette closed while typing arg", pal.hidden === true);

// 9. submitting the full line runs it with the argument
d.querySelector("#send").click();
const last = FakeWS.last.sent[FakeWS.last.sent.length-1];
ok("arg command sends", last.type === "bash" && last.command === "git status");
console.log("      sent:", JSON.stringify(last));

// 10. unknown command is reported, not sent to pi
const n0 = FakeWS.last.sent.length;
type("/nope"); d.querySelector("#send").click();
const notes = [...d.querySelectorAll(".note")].map(x => x.textContent);
ok("unknown command handled locally", FakeWS.last.sent.length === n0);
ok("unknown command explained", notes.some(t => t.includes("/nope")));

// 11. help lists everything locally
type("/help"); key("Enter");
const help = [...d.querySelectorAll(".note")].pop().textContent;
ok("help lists commands", help.includes("/resume") && help.includes("/bash <command>"));

// 12. plain prompts still work
type("arregla el login");
d.querySelector("#send").click();
const p = FakeWS.last.sent[FakeWS.last.sent.length-1];
ok("plain prompt still sends", p.type === "prompt" && p.message === "arregla el login");
