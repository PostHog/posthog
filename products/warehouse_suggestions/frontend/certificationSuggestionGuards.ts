import type { WarehouseSuggestionApi } from './generated/api.schemas'
import { isDeprecatePayload } from './suggestionCopy'
import { catalogEditBlockedReason } from './warehouseSuggestionsLogic'

const EDIT_ACCESS_REASON = 'You need edit access to this view or table'
const WORKING_REASON = 'Working'

export interface CertificationSuggestionGuards {
    isTable: boolean
    confirmsFirst: boolean
    acceptBlockedReason: string | undefined
    dismissBlockedReason: string | undefined
}

export function certificationSuggestionGuards(
    suggestion: WarehouseSuggestionApi,
    leaving: boolean,
    inFlight: boolean
): CertificationSuggestionGuards {
    const isTable = suggestion.subject_kind === 'table'
    const confirmsFirst = isDeprecatePayload(suggestion.payload) && !isTable
    const blockedReason = !suggestion.can_act ? EDIT_ACCESS_REASON : leaving ? WORKING_REASON : undefined
    return {
        isTable,
        confirmsFirst,
        acceptBlockedReason: blockedReason ?? (confirmsFirst ? undefined : catalogEditBlockedReason()),
        dismissBlockedReason: blockedReason ?? (inFlight ? WORKING_REASON : undefined),
    }
}
