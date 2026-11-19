import type { HogFlowAction, HogFlowEdge } from './types'

const BRANCHING_ACTION_TYPES = ['conditional_branch', 'random_cohort_branch', 'wait_until_condition'] as const

// A wait can run without a timeout, and the duration field keeps a unit-only value such as "m"
// while its number input is empty. Neither names a window, so accept only the complete duration
// that the step schema accepts. The alternation is the grammar the API and the worker already
// share: it keeps each digit run owned by one quantifier, where `\d*\.?\d+` lets both claim the
// same digits and backtracks quadratically on a long stored value that never matches.
const COMPLETE_DURATION_PATTERN = /^([0-9]+(?:\.[0-9]+)?|\.[0-9]+)([dhms])$/

// The executor holds a wait to the ceiling of its unit, and the API stores a larger amount
// unchanged. Use the same ceilings here so the label names the window the wait really honors.
const MAX_WAIT_AMOUNT_FOR_UNIT: Record<string, number> = {
    d: 30,
    h: 24,
    m: 60,
    s: 60,
}

export function isBranchingAction(action: Pick<HogFlowAction, 'type'>): boolean {
    return BRANCHING_ACTION_TYPES.includes(action.type as (typeof BRANCHING_ACTION_TYPES)[number])
}

function getWaitTimeoutLabel(maxWaitDuration: string | undefined): string | null {
    const parts = COMPLETE_DURATION_PATTERN.exec(maxWaitDuration ?? '')
    if (!parts) {
        return null
    }
    const [, amount, unit] = parts
    return `${Math.min(parseFloat(amount), MAX_WAIT_AMOUNT_FOR_UNIT[unit])}${unit}`
}

export function getWorkflowBranchLabel(action: HogFlowAction | undefined, edge: HogFlowEdge): string {
    if (action?.type === 'wait_until_condition') {
        if (edge.type === 'continue') {
            const timeout = getWaitTimeoutLabel(action.config.max_wait_duration)
            return timeout ? `No match within ${timeout}` : 'No match'
        }
        const { condition, events } = action.config
        if (condition?.name) {
            return condition.name
        }
        // The editor leaves an entry behind when the last event is removed, and the runtime skips
        // an entry that targets no event and no action. Such an entry cannot resolve the wait, so
        // it must not name an event here.
        const waitsForEvent = events?.some(
            (eventConfig) =>
                (eventConfig.filters?.events?.length ?? 0) > 0 || (eventConfig.filters?.actions?.length ?? 0) > 0
        )
        if (!waitsForEvent) {
            return 'Condition matched'
        }
        // The property condition and the events resolve the wait through this same edge, so a wait
        // that sets both must not name only one of them.
        const filters = condition?.filters
        const hasConditionFilters =
            (filters?.properties?.length ?? 0) > 0 ||
            (filters?.events?.length ?? 0) > 0 ||
            (filters?.actions?.length ?? 0) > 0
        return hasConditionFilters ? 'Condition or event matched' : 'Event received'
    }
    if (edge.type === 'continue') {
        // A random cohort split scales its weights to their total and always picks a cohort, so this
        // edge carries the leftover of an unusable split rather than a share of the traffic.
        return action?.type === 'random_cohort_branch' ? 'Fallback if no cohort has traffic' : 'No match'
    }

    if (!action) {
        return `If condition #${(edge.index ?? 0) + 1} matches`
    }

    switch (action.type) {
        case 'random_cohort_branch':
            return action.config.cohorts?.[edge.index ?? 0]?.name || `If cohort #${(edge.index ?? 0) + 1} matches`
        case 'conditional_branch':
            return action.config.conditions?.[edge.index ?? 0]?.name || `If condition #${(edge.index ?? 0) + 1} matches`
        default:
            return `If condition #${(edge.index ?? 0) + 1} matches`
    }
}
