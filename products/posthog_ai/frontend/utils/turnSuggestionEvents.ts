import posthog from 'posthog-js'

import type { TurnSuggestion } from '../types/streamTypes'

export interface TurnSuggestionEventContext {
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

export function captureTurnSuggestionShown(context: TurnSuggestionEventContext, suggestion: TurnSuggestion): void {
    posthog.capture('posthog ai turn suggestion shown', turnSuggestionEventProperties(context, suggestion))
}

export function captureTurnSuggestionDismissed(context: TurnSuggestionEventContext, suggestion: TurnSuggestion): void {
    posthog.capture('posthog ai turn suggestion dismissed', turnSuggestionEventProperties(context, suggestion))
}

/** The card went away because the conversation moved on, with no click and no dismissal. */
export function captureTurnSuggestionSuperseded(context: TurnSuggestionEventContext, suggestion: TurnSuggestion): void {
    posthog.capture('posthog ai turn suggestion superseded', turnSuggestionEventProperties(context, suggestion))
}
