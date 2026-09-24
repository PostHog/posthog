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

/**
 * The card's lifecycle: `superseded` is the card going away because the conversation moved on, and
 * `extra` on `accepted` carries what the kind created (a skill name, a notebook id, an alert bound).
 */
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
