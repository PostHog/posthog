import type { HogFlowAction, HogFlowEdge } from '../types'

export type AiDecisionAction = Extract<HogFlowAction, { type: 'ai_decision' }>
export type AiDecisionConfig = AiDecisionAction['config']
export type AiDecisionAnswerType = AiDecisionConfig['answer_type']
export type AiDecisionOption = NonNullable<AiDecisionConfig['options']>[number]

const AI_DECISION_FAILED_LABEL = 'If the decision fails'
export const AI_DECISION_UNSURE_LABEL = 'Unsure'
export const MIN_AI_DECISION_OPTIONS = 2
export const MAX_AI_DECISION_OPTIONS = 16

const YES_NO_ANSWER_LABELS = ['Yes', 'No']

// The server's defaults for a config saved without them (AIDecisionConfigSerializer).
const DEFAULT_YES_THRESHOLD = 50
const DEFAULT_NO_THRESHOLD = 20
const DEFAULT_MIN_PICK_PROBABILITY = 60

interface AiDecisionThresholds {
    yesThreshold: number
    noThreshold: number
    minPickProbability: number
}

export function getAiDecisionThresholds(config: AiDecisionConfig): AiDecisionThresholds {
    return {
        yesThreshold: config.yes_threshold ?? DEFAULT_YES_THRESHOLD,
        noThreshold: config.no_threshold ?? DEFAULT_NO_THRESHOLD,
        minPickProbability: config.min_pick_probability ?? DEFAULT_MIN_PICK_PROBABILITY,
    }
}

export function getAiDecisionOptions(config: AiDecisionConfig): AiDecisionOption[] {
    return config.options ?? []
}

/** One label per answer output, in branch edge order. */
export function getAiDecisionAnswerLabels(config: AiDecisionConfig): string[] {
    if (config.answer_type === 'yes_no') {
        return YES_NO_ANSWER_LABELS
    }
    return getAiDecisionOptions(config).map((option, index) => option.name.trim() || `Option ${index + 1}`)
}

/** One label per branch edge: the answers, then Unsure when it is on. */
function getAiDecisionBranchLabels(config: AiDecisionConfig): string[] {
    const answers = getAiDecisionAnswerLabels(config)
    return config.unsure_enabled ? [...answers, AI_DECISION_UNSURE_LABEL] : answers
}

export function getAiDecisionEdgeLabel(config: AiDecisionConfig, edge: HogFlowEdge): string {
    if (edge.type === 'continue') {
        return AI_DECISION_FAILED_LABEL
    }
    const index = edge.index ?? 0
    return getAiDecisionBranchLabels(config)[index] ?? `Answer ${index + 1}`
}

/** The answers a mocked test run can be told to give, as the runtime names them. */
export function getAiDecisionMockAnswerOptions(config: AiDecisionConfig): { value: string; label: string }[] {
    const answers =
        config.answer_type === 'yes_no'
            ? YES_NO_ANSWER_LABELS.map((label) => ({ value: label.toLowerCase(), label }))
            : getAiDecisionOptions(config)
                  .filter((option) => option.name.trim())
                  .map((option) => ({ value: option.name, label: option.name }))
    return config.unsure_enabled ? [...answers, { value: 'unsure', label: AI_DECISION_UNSURE_LABEL }] : answers
}

const EMPTY_OPTION: AiDecisionOption = { name: '' }

/**
 * Yes or no keeps only the named options, because the server rejects a blank option name on any answer
 * type. Pick one starts from those, padded to the minimum number of rows.
 */
export function withAiDecisionAnswerType(config: AiDecisionConfig, answerType: AiDecisionAnswerType): AiDecisionConfig {
    const namedOptions = getAiDecisionOptions(config).filter((option) => option.name.trim())
    const options =
        answerType === 'yes_no'
            ? namedOptions
            : [
                  ...getAiDecisionOptions(config),
                  ...Array(Math.max(0, MIN_AI_DECISION_OPTIONS - getAiDecisionOptions(config).length)).fill(
                      EMPTY_OPTION
                  ),
              ]
    return { ...config, answer_type: answerType, options }
}

/** The server rejects a yes or no Unsure band whose no threshold is not below the yes threshold. */
export function withAiDecisionUnsure(config: AiDecisionConfig, enabled: boolean): AiDecisionConfig {
    const { yesThreshold, noThreshold } = getAiDecisionThresholds(config)
    if (!enabled || config.answer_type !== 'yes_no' || noThreshold < yesThreshold) {
        return { ...config, unsure_enabled: enabled }
    }
    const nextYesThreshold = Math.max(yesThreshold, 2)
    return {
        ...config,
        unsure_enabled: true,
        yes_threshold: nextYesThreshold,
        no_threshold: nextYesThreshold - 1,
    }
}

export function withAiDecisionOptionAdded(config: AiDecisionConfig): AiDecisionConfig {
    return { ...config, options: [...getAiDecisionOptions(config), EMPTY_OPTION] }
}

export function withAiDecisionOptionRemoved(config: AiDecisionConfig, index: number): AiDecisionConfig {
    return { ...config, options: getAiDecisionOptions(config).filter((_, i) => i !== index) }
}

function getAiDecisionAnswerCount(config: AiDecisionConfig): number {
    return getAiDecisionAnswerLabels(config).length
}

/**
 * For each branch edge of the next config, the index of the current branch edge whose step it keeps,
 * or null for a new edge. Answers keep their position, except after the removed option, and Unsure
 * stays last.
 */
function carryOverBranchIndexes(
    current: AiDecisionConfig,
    next: AiDecisionConfig,
    removedAnswerIndex?: number
): (number | null)[] {
    const currentAnswerCount = getAiDecisionAnswerCount(current)
    const keptAnswerIndexes = Array.from({ length: currentAnswerCount }, (_, index) => index).filter(
        (index) => index !== removedAnswerIndex
    )
    const answerIndexes = Array.from(
        { length: getAiDecisionAnswerCount(next) },
        (_, index) => keptAnswerIndexes[index] ?? null
    )
    if (!next.unsure_enabled) {
        return answerIndexes
    }
    return [...answerIndexes, current.unsure_enabled ? currentAnswerCount : null]
}

export interface AiDecisionBranchEdgesPlan {
    branchEdges: HogFlowEdge[]
    droppedEdges: HogFlowEdge[]
}

/**
 * The branch edges a decision step needs after its config changes. A new edge leads where the step's
 * failure path leads, the way a new condition does on a conditional branch.
 */
export function planAiDecisionBranchEdges(
    actionId: string,
    actionEdges: HogFlowEdge[],
    current: AiDecisionConfig,
    next: AiDecisionConfig,
    removedAnswerIndex?: number
): AiDecisionBranchEdgesPlan {
    const currentBranchEdges = actionEdges.filter((edge) => edge.from === actionId && edge.type === 'branch')
    const edgeAt = (index: number): HogFlowEdge | undefined => currentBranchEdges.find((edge) => edge.index === index)
    const failedEdge = actionEdges.find((edge) => edge.from === actionId && edge.type === 'continue')
    const newEdgeTarget = failedEdge?.to ?? currentBranchEdges[0]?.to ?? ''

    const carriedIndexes = carryOverBranchIndexes(current, next, removedAnswerIndex)
    const branchEdges = carriedIndexes.map((carriedIndex, index) => ({
        from: actionId,
        to: (carriedIndex === null ? undefined : edgeAt(carriedIndex)?.to) ?? newEdgeTarget,
        type: 'branch' as const,
        index,
    }))
    const droppedEdges = currentBranchEdges.filter((edge) => !carriedIndexes.includes(edge.index ?? 0))
    return { branchEdges, droppedEdges }
}
