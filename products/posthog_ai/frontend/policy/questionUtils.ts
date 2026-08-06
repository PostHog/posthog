/**
 * Parsing + answer helpers for the sandbox `AskUserQuestion` flow, ported from Twig
 * (`packages/agent/src/adapters/claude/questions/utils.ts` and the mobile `QuestionCard`).
 *
 * In the sandbox runtime the agent asks the user to pick between options via the Claude built-in
 * `AskUserQuestion`. Twig routes it through the ACP permission framework: a single
 * `permission_request` carries `toolCall._meta.codeToolKind === 'question'` + `_meta.questions`, and
 * the answer is returned on the existing `permission_response` command as an `answers` map keyed by
 * question text. These helpers are shared by `runStreamLogic` (parsing the request), the input
 * overlay (`QuestionInput`, building the reply), and the thread recap (`QuestionRenderer`).
 */

/** The `option_${idx}` ids Twig's `buildQuestionOptions` mints for the first question's options. */
export const SANDBOX_QUESTION_OPTION_PREFIX = 'option_'

/** One choice the agent offered for a question. */
export interface AgentQuestionOption {
    label: string
    description?: string
}

/** One question parsed from an `AskUserQuestion` permission request or tool call. */
export interface AgentQuestion {
    question: string
    /** Short chip label (≤12 chars in the tool schema) shown above the question. */
    header?: string
    multiSelect: boolean
    options: AgentQuestionOption[]
}

function asRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

function parseOptions(raw: unknown): AgentQuestionOption[] {
    if (!Array.isArray(raw)) {
        return []
    }
    const options: AgentQuestionOption[] = []
    for (const entry of raw) {
        const record = asRecord(entry)
        if (!record || typeof record.label !== 'string') {
            continue
        }
        options.push({
            label: record.label,
            description: typeof record.description === 'string' && record.description ? record.description : undefined,
        })
    }
    return options
}

function parseQuestionItem(record: Record<string, unknown>): AgentQuestion | null {
    if (typeof record.question !== 'string') {
        return null
    }
    return {
        question: record.question,
        header: typeof record.header === 'string' && record.header ? record.header : undefined,
        multiSelect: record.multiSelect === true,
        options: parseOptions(record.options),
    }
}

/**
 * Parse the questions out of an `AskUserQuestion` payload. Accepts Twig's two input shapes
 * (`normalizeAskUserQuestionInput`): the preferred `{ questions: [...] }`, or a single
 * `{ question, header, options, multiSelect }`. Returns `[]` when nothing parseable is present.
 */
export function parseSandboxQuestions(raw: unknown): AgentQuestion[] {
    const record = asRecord(raw)
    if (!record) {
        return []
    }
    if (Array.isArray(record.questions)) {
        const questions: AgentQuestion[] = []
        for (const entry of record.questions) {
            const itemRecord = asRecord(entry)
            const item = itemRecord ? parseQuestionItem(itemRecord) : null
            if (item) {
                questions.push(item)
            }
        }
        return questions
    }
    const single = parseQuestionItem(record)
    return single ? [single] : []
}

/**
 * Per-question answers keyed by question text, read from the tool result. The result may be the
 * bare object or wrapped under an `output` envelope; array values (multi-select) are joined.
 */
export function parseSandboxQuestionAnswers(result: unknown): Record<string, string> {
    const outer = asRecord(result)
    for (const candidate of [outer, asRecord(outer?.output)]) {
        const map = asRecord(candidate?.answers)
        if (!map) {
            continue
        }
        const answers: Record<string, string> = {}
        for (const [key, value] of Object.entries(map)) {
            if (typeof value === 'string' && value.trim()) {
                answers[key] = value.trim()
            } else if (Array.isArray(value)) {
                const joined = value
                    .filter((v): v is string => typeof v === 'string' && v.trim().length > 0)
                    .map((v) => v.trim())
                    .join(', ')
                if (joined) {
                    answers[key] = joined
                }
            }
        }
        if (Object.keys(answers).length) {
            return answers
        }
    }
    return {}
}

/**
 * A single joined answer string for the compact recap — Twig's `extractAnswer`. Falls back through
 * `answer` / `answers` (joined) / `text` / `content` so an answer is shown even when the result
 * doesn't match the per-question map shape.
 */
export function extractSandboxQuestionAnswer(result: unknown): string | null {
    if (typeof result === 'string') {
        return result.trim() || null
    }
    const record = asRecord(result)
    if (!record) {
        return null
    }
    if (typeof record.answer === 'string' && record.answer.trim()) {
        return record.answer.trim()
    }
    const answers = asRecord(record.answers)
    if (answers) {
        const joined = Object.values(answers)
            .filter((v): v is string => typeof v === 'string' && v.trim().length > 0)
            .map((v) => v.trim())
            .join(', ')
        if (joined) {
            return joined
        }
    }
    if (typeof record.text === 'string' && record.text.trim()) {
        return record.text.trim()
    }
    if (typeof record.content === 'string' && record.content.trim()) {
        return record.content.trim()
    }
    return null
}

/**
 * The ACP `optionId` to send on the reply. Twig builds options server-side as `option_${idx}` over
 * the FIRST question's options; pick the index of the first selected label, falling back to
 * `option_0` for a free-typed ("Other") answer that matches no option. The `answers` map carries the
 * real content for the agent — `optionId` only has to be a valid offered option.
 */
export function deriveQuestionOptionId(question: AgentQuestion, selectedLabels: string[]): string {
    const first = selectedLabels[0]
    const idx = first !== undefined ? question.options.findIndex((o) => o.label === first) : -1
    return `${SANDBOX_QUESTION_OPTION_PREFIX}${idx >= 0 ? idx : 0}`
}
