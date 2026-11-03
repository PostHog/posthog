import { userHasAccess } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { WarehouseSuggestionApi } from './generated/api.schemas'
import { isDeprecatePayload } from './suggestionCopy'

const EDIT_ACCESS_REASON = 'You need edit access to this view or table'
const CATALOG_EDIT_ACCESS_REASON = 'You need edit access to the data catalog'
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
        acceptBlockedReason:
            blockedReason ??
            (userHasAccess(AccessControlResourceType.DataCatalog, AccessControlLevel.Editor)
                ? undefined
                : CATALOG_EDIT_ACCESS_REASON),
        dismissBlockedReason: blockedReason ?? (inFlight ? WORKING_REASON : undefined),
    }
}
