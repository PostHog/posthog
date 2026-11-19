import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

// Turning reviews on, the digest, and connecting GitHub need editor. Turning reviews off and changing
// when they run need manager, because those undo or narrow a review decision.
//
// The level comes from the API rather than the app context, because the app context answers for the
// environment in the URL while these rows belong to its parent project. Undefined when no repository
// has loaded yet, which sends the check back to the app context, so a team with no rows can still
// add its first repository.
export function managerDisabledReason(level: AccessControlLevel | undefined): string | null {
    const reason = getAccessControlDisabledReason(
        AccessControlResourceType.CodeReviewApproval,
        AccessControlLevel.Manager,
        level
    )
    return reason ? 'Only auto-approval managers can change this' : null
}

export function editorDisabledReason(level: AccessControlLevel | undefined): string | null {
    const reason = getAccessControlDisabledReason(
        AccessControlResourceType.CodeReviewApproval,
        AccessControlLevel.Editor,
        level
    )
    return reason ? 'Only auto-approval editors and managers can change this' : null
}
