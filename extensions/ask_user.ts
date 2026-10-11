/**
 * ask_user: the agent asks the user one to four questions with options.
 *
 * Loaded by pi remote with `pi -e` when the "Ask the user" switch is on.
 * Based on pi's examples/extensions/questionnaire.ts (MIT), which draws its
 * UI with ctx.ui.custom(): that call does not exist in RPC mode. Here, in
 * RPC, the whole questionnaire travels as ONE `editor` dialog: the title is
 * a marker pi remote recognises, the prefill carries the questions as JSON
 * and the reply (free text, the only dialog whose answer is) carries every
 * answer back as JSON. In the TUI it falls back to one select per question.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const MARK = "pi-remote:ask_user";

interface Option {
	label: string;
	description?: string;
}

interface Question {
	question: string;
	header?: string;
	options: Option[];
	recommended?: number;
	multiSelect?: boolean;
}

interface Answer {
	selected?: string[];
	other?: string;
	skipped?: boolean;
}

const OptionSchema = Type.Object({
	label: Type.String({ description: "Short option text, 1-5 words" }),
	description: Type.Optional(Type.String({ description: "One line on what this option means or implies" })),
});

const QuestionSchema = Type.Object({
	question: Type.String({ description: "The full question, ending with a question mark" }),
	header: Type.Optional(Type.String({ description: "Very short topic label, e.g. 'Storage', 'Scope'" })),
	options: Type.Array(OptionSchema, { description: "2 to 4 distinct choices. Do not add an 'Other' option: the user can always write one" }),
	recommended: Type.Optional(Type.Number({ description: "1-based number of the option you recommend, if any" })),
	multiSelect: Type.Optional(Type.Boolean({ description: "true if several options can be chosen together" })),
});

const Params = Type.Object({
	questions: Type.Array(QuestionSchema, { description: "1 to 4 questions" }),
});

// details: what pi remote reads back to rebuild the answered card from history
function text(t: string, details: { answers?: Answer[]; cancelled?: boolean } = {}) {
	return { content: [{ type: "text" as const, text: t }], details };
}

// what the model reads back
function summary(questions: Question[], answers: Answer[]): string {
	return questions
		.map((q, i) => {
			const a = answers[i] || {};
			const head = `Q${i + 1} (${q.header || q.question})`;
			if (a.skipped) return `${head}: user skipped this question`;
			const parts: string[] = [];
			if (a.selected && a.selected.length) parts.push(`user selected: ${a.selected.join(", ")}`);
			if (a.other && a.other.trim()) parts.push(`user wrote: ${a.other.trim()}`);
			return `${head}: ${parts.join("; ") || "no answer"}`;
		})
		.join("\n");
}

export default function askUser(pi: ExtensionAPI) {
	pi.registerTool({
		name: "ask_user",
		label: "Ask the user",
		description:
			"Ask the user 1 to 4 multiple-choice questions and wait for the answers. " +
			"Use it only when a real decision depends on the user's preference and you cannot " +
			"settle it from the request, the code or a sensible default. Do not use it to ask " +
			"for permission or to confirm obvious steps. The user can always pick an option, " +
			"write their own answer or skip a question.",
		parameters: Params,

		async execute(_id, params, signal, _onUpdate, ctx) {
			const questions = (params.questions as Question[]).slice(0, 4);
			if (!questions.length) return text("Error: no questions given");
			if (!ctx.hasUI) return text("Error: no user interface to ask through");

			let answers: Answer[] = [];
			if (ctx.mode === "rpc") {
				// the editor dialog has no abort option: a stopped turn must not
				// wait forever for a card nobody will answer
				const aborted = new Promise<undefined>((res) => {
					if (signal?.aborted) return res(undefined);
					signal?.addEventListener("abort", () => res(undefined), { once: true });
				});
				const raw = await Promise.race([
					ctx.ui.editor(MARK, JSON.stringify({ questions })),
					aborted,
				]);
				if (raw === undefined)
					return text("The user dismissed the questions without answering", { cancelled: true });
				try {
					const parsed = JSON.parse(raw);
					answers = Array.isArray(parsed?.answers) ? parsed.answers : [];
				} catch {
					// someone typed plain text into the dialog: pass it on as is
					return text(`The user answered: ${raw}`);
				}
			} else {
				for (const q of questions) {
					const labels = q.options.map((o, i) =>
						i + 1 === q.recommended ? `${o.label} (recommended)` : o.label,
					);
					const other = "Something else...";
					const pick = await ctx.ui.select(q.question, [...labels, other], { signal });
					if (pick === undefined)
						return text("The user dismissed the questions without answering", { cancelled: true });
					if (pick === other) {
						const t = await ctx.ui.input(q.question, "", { signal });
						answers.push(t ? { other: t } : { skipped: true });
					} else {
						answers.push({ selected: [q.options[labels.indexOf(pick)].label] });
					}
				}
			}
			return text(summary(questions, answers), { answers });
		},
	});
}
