import { turnSuggestionsResolveCreate } from '../generated/api'
import type { TurnSuggestionResolutionEnumApi } from '../generated/api.schemas'

/**
 * Records a dismissed or accepted card, so a reload keeps it hidden and a dismissal mutes the
 * conversation server-side. Best effort: the card already reacted locally, and a lost write only
 * means a reload can show the card again.
 */
export function recordTurnSuggestionResolution(
    projectId: number | null,
    card: { sessionId: string; turnIndex: number },
    resolution: TurnSuggestionResolutionEnumApi
): void {
    if (projectId === null) {
        return
    }
    turnSuggestionsResolveCreate(String(projectId), {
        task_id: card.sessionId,
        turn_index: card.turnIndex,
        resolution,
    }).catch(() => undefined)
}
