/**
 * Discovery hints appended to successful tool results.
 *
 * Two kinds, keyed off the tool name (the success-path counterpart of
 * `getToolRecoveryHint`, which only fires on 5xx errors):
 *
 * - Empty-state hints: a query-style tool returned zero rows. For products
 *   that need instrumentation (error tracking, logs, replay, AI observability)
 *   an empty result often means "not set up yet", not "nothing matched" — so
 *   instead of a bare empty array the agent gets pointed at the skill that
 *   gets data flowing, plus the mundane alternative (widen the date range).
 *
 * - Related-capability hints: the result is non-empty and there is an adjacent
 *   capability the agent is unlikely to know about at this point of use (error
 *   alerts after listing issues, subscriptions after creating an insight).
 *
 * Both registries are opt-in per tool: emptiness is not intrinsically
 * distinguishable from "correctly filtered to nothing", and a blanket hint on
 * every tool would be noise. Keep entries to one short paragraph and only add
 * tools where the adjacent capability is a genuine next step, not marketing.
 */

/**
 * Fired when the tool result is empty (see `isEmptyToolResult`). Wording rule:
 * lead with the not-instrumented-yet explanation and its skill, then give the
 * ordinary explanation (filters/date range) so the agent doesn't push setup
 * docs at a user who just over-filtered.
 */
const EMPTY_STATE_HINTS: Record<string, string> = {
    'query-error-tracking-issues-list':
        'No issues matched. If this project has never captured exceptions, error tracking may not be instrumented yet — load the `instrument-error-tracking` skill to set it up. If issues normally show up here, widen the `dateRange` or loosen the filters instead.',
    'query-logs':
        'No log rows matched. If this project has never ingested logs, load the `instrument-logs` skill to start shipping them. Otherwise widen the `dateRange` or drop filters — `logs-count` is a cheap way to check whether any logs exist at all.',
    'query-session-recordings-list':
        'No recordings matched. If session replay has never captured anything here, load the `diagnosing-missing-recordings` skill to check SDK setup, sampling, and capture settings. Otherwise widen the date range or loosen the filters.',
    'get-llm-total-costs-for-project':
        'No LLM cost data found. If AI observability is not capturing `$ai_generation` events yet, load the `instrument-llm-analytics` skill to wire it up. Otherwise widen the date range.',
}

/** Fired when the tool result is non-empty: the adjacent capability to reach for next. */
const RELATED_CAPABILITY_HINTS: Record<string, string> = {
    'query-error-tracking-issues-list':
        'Related: error alerts can notify Slack or a webhook when an issue is created, reopens, or starts spiking — load the `authoring-error-tracking-alerts` skill to set one up.',
    'query-logs':
        'Related: a check like this can run continuously as a log alert — load the `authoring-log-alerts` skill to author a low-noise one.',
    'get-llm-total-costs-for-project':
        'Related: to explain who or what drives this spend, load the `analyzing-expensive-users` skill.',
    'insight-create':
        'Related: this insight can go on a dashboard (`building-a-dashboard` skill) or be delivered to email/Slack on a schedule (`managing-subscriptions` skill).',
}

/**
 * Empty means "zero rows", in the two shapes the registered tools return:
 * a bare array, or the standardized `{ results: [...] }` envelope produced by
 * `withPostHogUrl` / `pickResponseFields` / the query-wrapper factory. Any
 * other shape is treated as non-empty — hints only register tools whose
 * shapes are known, so this never has to guess.
 */
export function isEmptyToolResult(handlerResult: unknown): boolean {
    if (Array.isArray(handlerResult)) {
        return handlerResult.length === 0
    }
    if (typeof handlerResult === 'object' && handlerResult !== null) {
        const results = (handlerResult as Record<string, unknown>).results
        return Array.isArray(results) && results.length === 0
    }
    return false
}

interface DiscoveryHintInput {
    /** The tool that produced the result. */
    toolName: string
    /** Raw handler return value, before serialization. */
    handlerResult: unknown
}

/**
 * Returns the discovery hint for a successful tool call, or `undefined` when
 * none is registered. At most one hint fires per call: the empty-state hint
 * when the result is empty, the related-capability hint otherwise.
 */
export function getDiscoveryHint({ toolName, handlerResult }: DiscoveryHintInput): string | undefined {
    if (isEmptyToolResult(handlerResult)) {
        return EMPTY_STATE_HINTS[toolName]
    }
    return RELATED_CAPABILITY_HINTS[toolName]
}
