import { turnSuggestionsResolveCreate } from '../generated/api'
import type { TurnSuggestionResolutionEnumApi } from '../generated/api.schemas'
import type { TurnSuggestion } from '../types/streamTypes'

/**
 * Records a dismissed or accepted card in the offer ledger, so a reload keeps it hidden and a
 * dismissal mutes the conversation server-side. Best effort: the card already closed locally, and a
 * lost write only means a reload can show the card again.
 */
export function recordTurnSuggestionResolution(
    projectId: number | null,
    sessionId: string,
    suggestion: TurnSuggestion,
    resolution: TurnSuggestionResolutionEnumApi
): void {
    if (projectId === null) {
        return
    }
    void turnSuggestionsResolveCreate(String(projectId), {
        task_id: sessionId,
        turn_index: suggestion.turnIndex,
        resolution,
    }).catch(() => undefined)
}
