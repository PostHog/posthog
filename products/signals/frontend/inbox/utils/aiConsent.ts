/**
 * Why the inbox's agent kickoffs (scout CTAs, Discuss, Create PR) are unavailable, or null when
 * they're allowed. The tasks backend has no consent check of its own, so an organization that
 * hasn't approved AI data processing is held back on the client, the same way the task composer
 * does it. Admins get told what to change; everyone else gets pointed at someone who can.
 */
export function aiConsentDisabledReason(
    dataProcessingAccepted: boolean,
    dataProcessingApprovalDisabledReason: string | null
): string | null {
    if (dataProcessingAccepted) {
        return null
    }
    return dataProcessingApprovalDisabledReason ?? 'Approve AI data processing in your organization settings first'
}
