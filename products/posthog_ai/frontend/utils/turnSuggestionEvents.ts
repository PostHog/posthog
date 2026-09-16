import type { TurnSuggestion } from '../types/streamTypes'

export interface TurnSuggestionEventContext {
    /** Task id backing the conversation. Lands in the events as `task_id`. */
    sessionId: string
    turnIndex: number
}

/** Shared properties of every card event, so one dashboard can split them by kind and intent. */
export function turnSuggestionEventProperties(
    context: TurnSuggestionEventContext,
    suggestion: TurnSuggestion
): Record<string, unknown> {
    return {
        ai_product: 'posthog_ai',
        agent_runtime: 'sandbox',
        task_id: context.sessionId,
        turn_index: context.turnIndex,
        suggestion_kind: suggestion.kind,
        intent: suggestion.intent,
        confidence: suggestion.confidence,
    }
}
