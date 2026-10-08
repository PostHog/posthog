import posthog from 'posthog-js'

import type { TurnSuggestion } from '../types/streamTypes'

export interface TurnSuggestionEventContext {
    sessionId: string
}

/** Shared properties of every card event, so one dashboard can split them by kind and intent. */
function turnSuggestionEventProperties(
    context: TurnSuggestionEventContext,
    suggestion: TurnSuggestion
): Record<string, unknown> {
    return {
        ai_product: 'posthog_ai',
        agent_runtime: 'sandbox',
        task_id: context.sessionId,
        turn_index: suggestion.turnIndex,
        suggestion_kind: suggestion.kind,
        intent: suggestion.intent,
        confidence: suggestion.confidence,
    }
}

export type TurnSuggestionEvent =
    | 'shown'
    | 'dismissed'
    | 'superseded'
    | 'accepted'
    | 'accept failed'
    | 'connect slack clicked'

export function captureTurnSuggestionEvent(
    event: TurnSuggestionEvent,
    context: TurnSuggestionEventContext,
    suggestion: TurnSuggestion,
    extra: Record<string, unknown> = {}
): void {
    posthog.capture(`posthog ai turn suggestion ${event}`, {
        ...turnSuggestionEventProperties(context, suggestion),
        ...extra,
    })
}
