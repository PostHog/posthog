import type { WarehouseSuggestionApi } from './generated/api.schemas'

const EDIT_ACCESS_REASON = 'You need edit access to this view'
const WORKING_REASON = 'Working'

export function suggestionBlockedReason(
    suggestion: WarehouseSuggestionApi,
    actionsInFlight: Record<string, boolean>,
    leaving: boolean
): string | undefined {
    if (!suggestion.can_act) {
        return EDIT_ACCESS_REASON
    }
    return actionsInFlight[suggestion.id] || leaving ? WORKING_REASON : undefined
}
