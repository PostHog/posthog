import { turnSuggestionsResolveCreate } from '../generated/api'
import type { TurnSuggestionResolutionEnumApi } from '../generated/api.schemas'
import type { TurnSuggestion } from '../types/streamTypes'

// Past the server's wait for the run log's append lock, which a busy agent can hold that long.
const RETRY_DELAY_MS = 10_000

/**
 * Records a dismissed or accepted card, so a reload keeps it hidden and a dismissal mutes the
 * conversation server-side. Best effort: the card already reacted locally, and a lost write only
 * means a reload can show the card again.
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
    // The suggestion's own turn counts user messages like the server does; the card's trailer index skips unanswered turns.
    const send = (): Promise<boolean> =>
        turnSuggestionsResolveCreate(String(projectId), {
            task_id: sessionId,
            turn_index: suggestion.turnIndex,
            resolution,
        }).then(({ recorded }) => recorded)
    // The server leaves the card open when the outcome misses the run log, so one later try can record it.
    send()
        .then((recorded) => {
            if (!recorded) {
                window.setTimeout(() => void send().catch(() => undefined), RETRY_DELAY_MS)
            }
        })
        .catch(() => undefined)
}
