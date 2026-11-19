import type { PermissionResponseParams } from '@/api/tasks'
import { asRecord } from '@/lib/records'
import type { DecisionAnswerInput, DecisionOption, DecisionQuestion } from '@/model/types'

import { extractAgentToolName, isPlanPermissionRequest } from './toolPolicy'
import type {
    AgentQuestion,
    AgentQuestionOption,
    PendingRequest,
    PendingRequestKind,
    PermissionOption,
    PermissionRecord,
} from './types'

const QUESTION_OPTION_PREFIX = 'option_'

const PLAN_APPROVAL_OPTIONS: Record<string, Omit<DecisionOption, 'id'>> = {
    auto: {
        title: 'Approve the plan',
        meta: 'Accepts edits and commands. Asks before changing live data.',
    },
    bypassPermissions: {
        title: 'Approve in full auto',
        meta: 'Can change or delete live data. Some tools still ask for approval.',
    },
}

function parseOption(raw: unknown): PermissionOption | null {
    const record = asRecord(raw)
    if (!record) {
        return null
    }
    const kind = String(record.kind ?? '')
    // Accept any non-empty kind: the vocabulary follows the agent adapter, and prefix matching
    // classifies it. Dropping unknown kinds would leave a request nobody can answer.
    if (typeof record.optionId !== 'string' || !kind) {
        return null
    }
    return {
        optionId: record.optionId,
        name: String(record.name ?? ''),
        kind,
        customInput: asRecord(record._meta)?.customInput === true,
    }
}

function parseQuestionOptions(raw: unknown): AgentQuestionOption[] {
    if (!Array.isArray(raw)) {
        return []
    }
    const options: AgentQuestionOption[] = []
    for (const entry of raw) {
        const record = asRecord(entry)
        if (record && typeof record.label === 'string') {
            options.push({
                label: record.label,
                ...(typeof record.description === 'string' && record.description
                    ? { description: record.description }
                    : {}),
            })
        }
    }
    return options
}

function parseQuestion(record: Record<string, unknown>): AgentQuestion | null {
    if (typeof record.question !== 'string') {
        return null
    }
    return {
        question: record.question,
        ...(typeof record.header === 'string' && record.header ? { header: record.header } : {}),
        multiSelect: record.multiSelect === true,
        options: parseQuestionOptions(record.options),
    }
}

/** Questions from `_meta`, in either shape the agent sends: `{questions: [...]}` or a single question. */
function parseQuestions(meta: Record<string, unknown>): AgentQuestion[] {
    if (Array.isArray(meta.questions)) {
        return meta.questions
            .map((entry) => {
                const record = asRecord(entry)
                return record ? parseQuestion(record) : null
            })
            .filter((question): question is AgentQuestion => question !== null)
    }
    const single = parseQuestion(meta)
    return single ? [single] : []
}

export function parsePermissionRequest(frame: unknown): PermissionRecord | null {
    const record = asRecord(frame)
    if (!record || typeof record.requestId !== 'string' || !record.requestId) {
        return null
    }
    const toolCall = asRecord(record.toolCall) ?? {}
    const toolCallId = String(toolCall.toolCallId ?? record.toolCallId ?? '')
    if (!toolCallId) {
        return null
    }
    const options = Array.isArray(record.options)
        ? record.options.map(parseOption).filter((option): option is PermissionOption => option !== null)
        : []
    if (options.length === 0) {
        return null
    }
    const meta = toolCall._meta
    const metaRecord = asRecord(meta) ?? {}
    const rawToolName = String(toolCall.toolName ?? '')
    const questions = metaRecord.codeToolKind === 'question' ? parseQuestions(metaRecord) : []
    const title = typeof toolCall.title === 'string' && toolCall.title ? toolCall.title : undefined
    return {
        requestId: record.requestId,
        requestDetails: JSON.stringify(toolCall, null, 2),
        toolCallId,
        toolName: extractAgentToolName(meta) ?? rawToolName,
        options,
        ...(title ? { title } : {}),
        ...(questions.length > 0 ? { questions } : {}),
        rawToolCall: {
            toolCallId,
            rawServerName: String(toolCall.serverName ?? 'posthog'),
            rawToolName,
            input: asRecord(toolCall.rawInput) ?? asRecord(toolCall.input) ?? {},
            ...(title ? { title } : {}),
            ...(typeof toolCall.kind === 'string' ? { kind: toolCall.kind } : {}),
            meta,
        },
    }
}

export function requestKind(record: PermissionRecord): PendingRequestKind {
    if (record.questions?.length) {
        return 'question'
    }
    if (record.rawToolCall.kind === 'switch_mode' || isPlanPermissionRequest(record)) {
        return 'plan'
    }
    return 'permission'
}

function optionTitle(option: PermissionOption): string {
    if (option.name) {
        return option.name
    }
    if (option.kind === 'allow_always') {
        return 'Always allow'
    }
    return option.kind.startsWith('allow') ? 'Allow' : 'Deny'
}

function planOptions(record: PermissionRecord): DecisionOption[] {
    const offered = new Set(record.options.map((option) => option.optionId))
    const modes = Object.keys(PLAN_APPROVAL_OPTIONS).filter((id) => offered.has(id))
    if (modes.length === 0) {
        // Unknown mode ids: show what the agent offered so the plan can still be answered.
        return record.options.map((option) => ({ id: option.optionId, title: optionTitle(option) }))
    }
    return modes.map((id) => ({ id, ...(PLAN_APPROVAL_OPTIONS[id] as Omit<DecisionOption, 'id'>) }))
}

export function decisionId(requestId: string, step: number): string {
    return step === 0 ? requestId : `${requestId}#${step}`
}

export function decisionQuestionFor(pending: PendingRequest, answered: readonly string[] = []): DecisionQuestion {
    const { record } = pending
    if (pending.kind === 'question' && record.questions) {
        const step = Math.min(answered.length, record.questions.length - 1)
        const question = record.questions[step] as AgentQuestion
        return {
            id: decisionId(record.requestId, step),
            question: question.question,
            options: question.options.map((option, index) => ({
                id: `${QUESTION_OPTION_PREFIX}${index}`,
                title: option.label,
                ...(option.description ? { meta: option.description } : {}),
            })),
        }
    }
    if (pending.kind === 'plan') {
        return {
            id: record.requestId,
            question: 'Approve the plan?',
            details: record.requestDetails ?? JSON.stringify(record.rawToolCall, null, 2),
            options: planOptions(record),
        }
    }
    const subject = record.title ?? record.toolName
    return {
        id: record.requestId,
        question: subject ? `Allow ${subject}?` : 'Allow this action?',
        details: record.requestDetails ?? JSON.stringify(record.rawToolCall, null, 2),
        options: record.options.map((option) => ({ id: option.optionId, title: optionTitle(option) })),
    }
}

export type AnswerPlan =
    | { type: 'next_question'; label: string }
    | { type: 'respond'; params: PermissionResponseParams }

function freeTextOption(options: PermissionOption[]): PermissionOption | undefined {
    return (
        options.find((option) => option.customInput) ??
        options.find((option) => !option.kind.startsWith('allow')) ??
        options[0]
    )
}

// For a question, `answers` carries the content keyed by question text, multi-select labels joined with ", ".
// `optionId` only has to be an offered option: the first question's pick, else `option_0`.
export function planAnswer(
    pending: PendingRequest,
    answered: readonly string[],
    input: DecisionAnswerInput
): AnswerPlan {
    const { record } = pending
    if (pending.kind === 'question' && record.questions) {
        const questions = record.questions
        const step = Math.min(answered.length, questions.length - 1)
        const current = questions[step] as AgentQuestion
        const pickedIndex = input.optionId?.startsWith(QUESTION_OPTION_PREFIX)
            ? Number(input.optionId.slice(QUESTION_OPTION_PREFIX.length))
            : -1
        const label = current.options[pickedIndex]?.label ?? input.text
        if (step < questions.length - 1) {
            return { type: 'next_question', label }
        }
        const labels = [...answered.slice(0, step), label]
        const answers: Record<string, string> = {}
        questions.forEach((question, index) => {
            const value = labels[index]
            if (value) {
                answers[question.question] = value
            }
        })
        const first = questions[0] as AgentQuestion
        const firstLabel = labels[0] ?? ''
        const firstIndex = first.options.findIndex((option) => option.label === firstLabel)
        const wanted = `${QUESTION_OPTION_PREFIX}${firstIndex >= 0 ? firstIndex : 0}`
        const optionId = record.options.some((option) => option.optionId === wanted)
            ? wanted
            : (record.options[0] as PermissionOption).optionId
        return {
            type: 'respond',
            params: {
                requestId: record.requestId,
                optionId,
                answers,
                ...(firstIndex === -1 && firstLabel ? { customInput: firstLabel } : {}),
            },
        }
    }
    if (input.optionId && record.options.some((option) => option.optionId === input.optionId)) {
        return { type: 'respond', params: { requestId: record.requestId, optionId: input.optionId } }
    }
    const option = freeTextOption(record.options) as PermissionOption
    return {
        type: 'respond',
        params: { requestId: record.requestId, optionId: option.optionId, customInput: input.text },
    }
}
