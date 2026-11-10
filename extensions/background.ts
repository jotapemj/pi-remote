/**
 * Background tasks: the agent starts long commands (builds, tests, flashing a
 * board) without waiting for them, keeps working or talking, and is told when
 * they end.
 *
 * Loaded by pi remote with `pi -e` when the "Background tasks" switch is on.
 * Each task is two files in a jobs folder: <id>.json (state) and <id>.log
 * (output). The command runs in a subshell wrapped by the same bash pi uses,
 * and the wrapper writes the exit code to <id>.code, so a pi that restarted
 * (project switch, /restart of pi alone) picks the task up again from disk.
 *
 * Safety: bg_run runs shell commands but is not called `bash`, so permission
 * rules written for `bash` do not see it. With pi-permission-system installed
 * and `shellTools.bg_run` in its config, that extension gates it with the bash
 * rules; otherwise this one asks every time (allow once / allow this command
 * for the session / deny), and denies when nobody can be asked. Commands run
 * in the project folder only; bg_log and bg_kill touch only tasks started here.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { spawn, spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const KIND = "pi-remote:bg";
const MAX_RUNNING = 3;
const WAIT_MAX = 120;            // seconds bg_wait may block
const WAKE_MAX = 5;              // agent wake-ups in a row without the user
const KEEP_DAYS = 7;
const POLL_MS = 2000;

export interface Job {
	id: number;
	label: string;
	command: string;
	cwd: string;
	pid: number;
	started: number;
	ended?: number;
	code?: number | null;
	status: "running" | "done" | "failed" | "killed";
	notified?: boolean;
}

export function jobsDir(): string {
	return process.env.PI_REMOTE_JOBS || path.join(os.homedir(), ".pi", "agent", "pi-remote-jobs");
}
const fileOf = (id: number, ext: string) => path.join(jobsDir(), `${id}.${ext}`);

export function readJob(id: number): Job | null {
	try {
		return JSON.parse(fs.readFileSync(fileOf(id, "json"), "utf8"));
	} catch {
		return null;
	}
}
function writeJob(j: Job) {
	const f = fileOf(j.id, "json");
	fs.writeFileSync(f + ".tmp", JSON.stringify(j));
	fs.renameSync(f + ".tmp", f);
}
export function allJobs(): Job[] {
	let names: string[] = [];
	try {
		names = fs.readdirSync(jobsDir());
	} catch {
		return [];
	}
	return names
		.filter((n) => /^\d+\.json$/.test(n))
		.map((n) => readJob(parseInt(n, 10)))
		.filter((j): j is Job => !!j)
		.sort((a, b) => a.id - b.id);
}
const sameDir = (a: string, b: string) =>
	path.resolve(a).toLowerCase() === path.resolve(b).toLowerCase();

/** Same lookup as pi's bash tool: shellPath, Git Bash, then bash on PATH. */
export function bashPath(): string {
	try {
		const s = JSON.parse(
			fs.readFileSync(path.join(os.homedir(), ".pi", "agent", "settings.json"), "utf8"),
		);
		if (s.shellPath) return String(s.shellPath).replace(/^~/, os.homedir());
	} catch {}
	if (process.platform === "win32") {
		for (const base of [process.env.ProgramFiles, process.env["ProgramFiles(x86)"]]) {
			if (!base) continue;
			const p = path.join(base, "Git", "bin", "bash.exe");
			if (fs.existsSync(p)) return p;
		}
	}
	return "bash";
}

function alive(pid: number): boolean {
	try {
		process.kill(pid, 0);
		return true;
	} catch (e: any) {
		return e?.code === "EPERM";
	}
}

/** Progress bars rewrite a line with \r and colour it with ANSI codes: keep
 * only what the line ends up showing, without escapes. */
export function cleanLog(raw: string): string[] {
	return raw
		.replace(/\x1b\[[0-9;?]*[ -\/]*[@-~]/g, "")
		.split(/\r?\n/)
		.map((l) => {
			const parts = l.split("\r");
			return parts[parts.length - 1];
		});
}
export function tail(id: number, n: number, grep?: string): string[] {
	let raw = "";
	try {
		const f = fileOf(id, "log");
		const size = fs.statSync(f).size;
		const fd = fs.openSync(f, "r");
		const len = Math.min(size, 256 * 1024);       // the end is what matters
		const buf = Buffer.alloc(len);
		fs.readSync(fd, buf, 0, len, size - len);
		fs.closeSync(fd);
		raw = buf.toString("utf8");
	} catch {
		return [];
	}
	let lines = cleanLog(raw);
	while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
	if (grep) {
		const g = grep.toLowerCase();
		lines = lines.filter((l) => l.toLowerCase().includes(g));
	}
	return lines.slice(-n);
}

/** Done, failed or gone: settle a running job from what is on disk. */
export function refresh(j: Job): Job {
	if (j.status !== "running") return j;
	let code: string | null = null;
	try {
		code = fs.readFileSync(fileOf(j.id, "code"), "utf8").trim();
	} catch {}
	if (code !== null && code !== "") {
		const c = parseInt(code, 10);
		Object.assign(j, { status: c === 0 ? "done" : "failed", code: c, ended: Date.now() });
		writeJob(j);
	} else if (!alive(j.pid)) {
		Object.assign(j, { status: "killed", code: null, ended: Date.now() });
		writeJob(j);
	}
	return j;
}

export function killJob(j: Job) {
	if (process.platform === "win32") {
		spawnSync("taskkill", ["/T", "/F", "/PID", String(j.pid)], { windowsHide: true });
	} else {
		try {
			process.kill(-j.pid, "SIGTERM");
		} catch {}
	}
	Object.assign(j, { status: "killed", code: null, ended: Date.now() });
	writeJob(j);
}

export function startJob(command: string, cwd: string, label?: string): Job {
	fs.mkdirSync(jobsDir(), { recursive: true });
	const id = allJobs().reduce((m, j) => Math.max(m, j.id), 0) + 1;
	const slash = (f: string) => f.replace(/\\/g, "/");
	// the command travels in the environment: no quoting to get wrong; the
	// subshell keeps an `exit` inside it from skipping the exit-code line.
	// bash redirects the output itself: on Windows a detached Git Bash could
	// not write to a file handle passed by Node (every echo failed)
	const child = spawn(
		bashPath(),
		["-c", '( eval "$PI_BG_CMD" ) > "$PI_BG_LOG" 2>&1 < /dev/null; echo $? > "$PI_BG_CODE"'],
		{
			cwd,
			detached: true,
			windowsHide: true,
			stdio: "ignore",
			env: { ...process.env, PI_BG_CMD: command,
			       PI_BG_LOG: slash(fileOf(id, "log")), PI_BG_CODE: slash(fileOf(id, "code")) },
		},
	);
	child.unref();
	const j: Job = {
		id,
		label: (label || command).slice(0, 80),
		command,
		cwd,
		pid: child.pid ?? 0,
		started: Date.now(),
		status: "running",
	};
	writeJob(j);
	return j;
}

function sweepOld() {
	const cut = Date.now() - KEEP_DAYS * 864e5;
	for (const j of allJobs()) {
		if (j.status !== "running" && (j.ended || j.started) < cut) {
			for (const ext of ["json", "log", "code"]) {
				try {
					fs.unlinkSync(fileOf(j.id, ext));
				} catch {}
			}
		}
	}
}

/** pi-permission-system installed and told bg_run is a shell: it gates the
 * command with the bash rules, and asking here too would ask twice. */
export function gatedByPermissionSystem(): boolean {
	const home = path.join(os.homedir(), ".pi", "agent");
	const cfg =
		process.env.PI_REMOTE_PERMCFG ||
		path.join(home, "extensions", "pi-permission-system", "config.json");
	const pkg = path.join(home, "npm", "node_modules", "@gotgenes", "pi-permission-system");
	if (!process.env.PI_REMOTE_PERMCFG && !fs.existsSync(pkg)) return false;
	try {
		const raw = fs.readFileSync(cfg, "utf8");
		let j: any;
		try {
			j = JSON.parse(raw);
		} catch {
			j = JSON.parse(raw.replace(/^\s*\/\/.*$/gm, ""));     // jsonc
		}
		return !!j?.shellTools?.bg_run;
	} catch {
		return false;
	}
}

const ago = (ms: number) => {
	const s = Math.round(ms / 1000);
	return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
};
export function describe(j: Job): string {
	const t = ago((j.ended || Date.now()) - j.started);
	const st =
		j.status === "running" ? `running for ${t}`
		: j.status === "killed" ? `stopped after ${t}`
		: `${j.status} (exit code ${j.code}) after ${t}`;
	return `#${j.id} ${j.label}: ${st}`;
}

const text = (t: string, details: object = {}) => ({
	content: [{ type: "text" as const, text: t }],
	details,
});

export default function background(pi: ExtensionAPI) {
	const allowed = new Set<string>();     // commands allowed for this session
	let cwd = process.cwd();
	let timer: ReturnType<typeof setInterval> | null = null;
	let wakes = 0;

	// each call looks at the folder it was made in; `cwd` is the session's
	const mine = (dir = cwd) => allJobs().filter((j) => sameDir(j.cwd, dir));
	const find = (id: number, dir: string) => {
		const j = readJob(id);
		return j && sameDir(j.cwd, dir) ? refresh(j) : null;
	};

	function announce(j: Job) {
		j.notified = true;
		writeJob(j);
		const last = tail(j.id, 15);
		const body =
			`Background task ${describe(j)}.` +
			(last.length ? `\nLast lines of its output:\n${last.join("\n")}` : "\nIt printed nothing.");
		// a chain of wake-ups with nobody reading: report it, do not wake again
		const wake = wakes < WAKE_MAX;
		if (wake) wakes++;
		pi.sendMessage(
			{ customType: KIND, content: body, display: true,
			  details: { id: j.id, status: j.status, code: j.code, label: j.label } },
			wake ? { triggerTurn: true, deliverAs: "followUp" } : { deliverAs: "nextTurn" },
		);
	}

	function poll() {
		for (const j of mine()) {
			refresh(j);
			if (j.status === "running" || j.notified) continue;
			// ended long ago while nobody was here: no reason to wake anyone
			if (Date.now() - (j.ended || 0) > 3600e3) {
				j.notified = true;
				writeJob(j);
			} else announce(j);
		}
	}

	pi.on("session_start", async (_e, ctx) => {
		cwd = ctx.cwd;
		sweepOld();
		if (!timer) timer = setInterval(poll, POLL_MS);
		poll();                               // what ended while pi was down
	});
	pi.on("session_shutdown", async () => {
		if (timer) clearInterval(timer);
		timer = null;                         // the tasks keep running
	});
	pi.on("input", async () => {
		wakes = 0;                            // the user is here again
	});

	pi.registerTool({
		name: "bg_run",
		label: "Run in background",
		description:
			"Start a long-running shell command (build, test suite, flashing, a dev server) " +
			"in the background and return immediately with a task id, instead of blocking " +
			"like bash does. Use it for anything that takes more than about a minute. " +
			"You will get a message when it ends; meanwhile keep working or answer the user. " +
			"Check on it with bg_list, bg_log or bg_wait; stop it with bg_kill. " +
			"For quick commands use bash instead. Runs in the project folder.",
		parameters: Type.Object({
			command: Type.String({ description: "The shell command, as you would pass to bash" }),
			label: Type.Optional(Type.String({ description: "Short name for the task, e.g. 'android build'" })),
		}),
		async execute(_id, params, signal, _u, ctx) {
			const command = String(params.command || "").trim();
			if (!command) return text("Error: empty command");
			const running = mine(ctx.cwd).map(refresh).filter((j) => j.status === "running");
			if (running.length >= MAX_RUNNING)
				return text(
					`Error: ${running.length} tasks are already running (limit ${MAX_RUNNING}). ` +
					`Wait for one or stop it with bg_kill.\n${running.map(describe).join("\n")}`,
				);
			if (!gatedByPermissionSystem() && !allowed.has(command)) {
				if (!ctx.hasUI) return text("Denied: there is no user to ask for permission");
				const once = "Allow once", session = "Allow this command for this session";
				const pick = await ctx.ui.select(
					`Run in the background?\n${command}`,
					[once, session, "Deny"],
					{ signal },
				);
				if (pick === session) allowed.add(command);
				else if (pick !== once) return text("Denied by the user", { denied: true });
			}
			const j = startJob(command, ctx.cwd, params.label as string | undefined);
			return text(
				`Started background task #${j.id} (${j.label}). You will be told when it ends. ` +
				`Use bg_log ${j.id} to read its output, bg_wait to wait a little, bg_kill to stop it.`,
				{ id: j.id },
			);
		},
	});

	pi.registerTool({
		name: "bg_list",
		label: "Background tasks",
		description: "List the background tasks of this project with their state and duration.",
		parameters: Type.Object({}),
		async execute(_id, _p, _s, _u, ctx) {
			const js = mine(ctx.cwd).map(refresh);
			return text(js.length ? js.map(describe).join("\n") : "No background tasks.");
		},
	});

	pi.registerTool({
		name: "bg_log",
		label: "Task output",
		description:
			"Read the end of a background task's output, cleaned of colours and progress bars. " +
			"Use grep to keep only matching lines (e.g. 'error', 'warning').",
		parameters: Type.Object({
			id: Type.Number({ description: "Task id" }),
			lines: Type.Optional(Type.Number({ description: "How many lines from the end (default 40, max 400)" })),
			grep: Type.Optional(Type.String({ description: "Only lines containing this text, case-insensitive" })),
		}),
		async execute(_id, params, _s, _u, ctx) {
			const j = find(Number(params.id), ctx.cwd);
			if (!j) return text(`Error: no task #${params.id} in this project`);
			const n = Math.max(1, Math.min(400, Number(params.lines) || 40));
			const out = tail(j.id, n, params.grep as string | undefined);
			return text(`${describe(j)}\n` + (out.length ? out.join("\n") : "(no output yet)"));
		},
	});

	pi.registerTool({
		name: "bg_wait",
		label: "Wait for task",
		description:
			`Wait up to ${WAIT_MAX} seconds for a background task to end, for when it is about to ` +
			"finish and the next step needs its result. Returns early when it ends.",
		parameters: Type.Object({
			id: Type.Number({ description: "Task id" }),
			seconds: Type.Optional(Type.Number({ description: `Most seconds to wait (default 30, max ${WAIT_MAX})` })),
		}),
		async execute(_id, params, signal, _u, ctx) {
			let j = find(Number(params.id), ctx.cwd);
			if (!j) return text(`Error: no task #${params.id} in this project`);
			const until = Date.now() + Math.min(WAIT_MAX, Number(params.seconds) || 30) * 1000;
			while (j.status === "running" && Date.now() < until && !signal?.aborted) {
				await new Promise((r) => setTimeout(r, 500));
				j = refresh(readJob(j.id) || j);
			}
			if (j.status !== "running" && !j.notified) {
				j.notified = true;                 // the result is in this reply
				writeJob(j);
			}
			return text(`${describe(j)}\n${tail(j.id, 15).join("\n")}`);
		},
	});

	pi.registerTool({
		name: "bg_kill",
		label: "Stop task",
		description: "Stop a running background task and everything it started.",
		parameters: Type.Object({ id: Type.Number({ description: "Task id" }) }),
		async execute(_id, params, _s, _u, ctx) {
			const j = find(Number(params.id), ctx.cwd);
			if (!j) return text(`Error: no task #${params.id} in this project`);
			if (j.status !== "running") return text(`Task ${describe(j)}: nothing to stop`);
			j.notified = true;                     // stopped on purpose: no wake-up
			killJob(j);
			return text(`Stopped task #${j.id} (${j.label}).`);
		},
	});
}
