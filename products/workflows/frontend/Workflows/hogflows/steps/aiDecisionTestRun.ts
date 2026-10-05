import { z } from 'zod'

import { AI_DECISION_UNSURE_LABEL, AiDecisionConfig, getAiDecisionAnswerLabels, getAiDecisionOptions } from './aiDecisionBranches'
import type { HogflowTestResult } from './types'

// The step's result as the workflow runtime returns it from a test run. A mocked run adds the rendered
// context and its size in bytes.
const AiDecisionResultSchema = z.object({
    answer: z.string(),
    probabilities: z.record(z.string(), z.number()),
    context: z.record(z.string(), z.unknown()).optional(),
    context_bytes: z.number().optional(),
})

const UNSURE_ANSWER = 'unsure'
const UNREADABLE_RESULT_MESSAGE = "The test finished, but its answer couldn't be read. Try again."
const FAILED_RUN_MESSAGE = 'The test run failed. Check the step settings and try again.'

export interface AiDecisionAnswerProbability {
    label: string
    percent: number
    chosen: boolean
}

export type AiDecisionTestOutcome =
    | { status: 'answered'; answers: AiDecisionAnswerProbability[]; pathLabel: string }
    | { status: 'failed'; message: string }

export type AiDecisionContextPreview =
    | { status: 'rendered'; context: Record<string, unknown>; bytes: number }
    | { status: 'failed'; message: string }

type ReadResult = { ok: true; result: z.infer<typeof AiDecisionResultSchema> } | { ok: false; message: string }

function readResult(testResult: HogflowTestResult): ReadResult {
    if (testResult.status === 'error') {
        return { ok: false, message: testResult.errors?.join(' ') || FAILED_RUN_MESSAGE }
    }
    const parsed = AiDecisionResultSchema.safeParse(testResult.execResult)
    return parsed.success ? { ok: true, result: parsed.data } : { ok: false, message: UNREADABLE_RESULT_MESSAGE }
}

/** The keys the model answers with, in answer order: yes and no, or the option names. */
function getAnswerKeys(config: AiDecisionConfig): string[] {
    return config.answer_type === 'yes_no' ? ['yes', 'no'] : getAiDecisionOptions(config).map((option) => option.name)
}

export function readAiDecisionTestOutcome(config: AiDecisionConfig, testResult: HogflowTestResult): AiDecisionTestOutcome {
    const read = readResult(testResult)
    if (!read.ok) {
        return { status: 'failed', message: read.message }
    }
    const { answer, probabilities } = read.result
    const labels = getAiDecisionAnswerLabels(config)
    const chosenIndex = getAnswerKeys(config).indexOf(answer)
    if (chosenIndex === -1 && answer !== UNSURE_ANSWER) {
        return { status: 'failed', message: UNREADABLE_RESULT_MESSAGE }
    }
    return {
        status: 'answered',
        answers: getAnswerKeys(config).map((key, index) => ({
            label: labels[index],
            percent: Math.round((probabilities[key] ?? 0) * 100),
            chosen: index === chosenIndex,
        })),
        pathLabel: chosenIndex === -1 ? AI_DECISION_UNSURE_LABEL : labels[chosenIndex],
    }
}

export function readAiDecisionContextPreview(testResult: HogflowTestResult): AiDecisionContextPreview {
    const read = readResult(testResult)
    if (!read.ok) {
        return { status: 'failed', message: read.message }
    }
    const { context, context_bytes } = read.result
    if (!context || context_bytes === undefined) {
        return { status: 'failed', message: UNREADABLE_RESULT_MESSAGE }
    }
    return { status: 'rendered', context, bytes: context_bytes }
}

export function getTestRunErrorMessage(error: unknown): string {
    if (error && typeof error === 'object' && 'detail' in error && typeof error.detail === 'string') {
        return error.detail
    }
    return FAILED_RUN_MESSAGE
}
