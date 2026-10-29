import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { EnrichedReviewer } from '../../types'

export interface ReviewerClaim {
    claimantUuid: string | null
    currentUserUuid: string | null
    claimable: boolean
    saving: boolean
    onSetClaimed: (claimed: boolean) => void
}

function isClaimant(reviewer: EnrichedReviewer, claim: ReviewerClaim): boolean {
    return !!reviewer.user && reviewer.user.uuid === claim.claimantUuid
}

export function reviewerClaimRemoveDisabledReason(
    reviewer: EnrichedReviewer,
    claim: ReviewerClaim | undefined,
    displayName: string
): string | undefined {
    if (!claim) {
        return undefined
    }
    if (!isClaimant(reviewer, claim)) {
        // A pending claim makes this row the claimant row, so the remove must wait for it.
        return claim.saving && !!reviewer.user && reviewer.user.uuid === claim.currentUserUuid ? 'Updating…' : undefined
    }
    return reviewer.user?.uuid === claim.currentUserUuid
        ? "You're working on this report. Unclaim it before you remove yourself."
        : `${displayName} is working on this report.`
}

export function SuggestedReviewerClaimControls({
    reviewer,
    claim,
}: {
    reviewer: EnrichedReviewer
    claim: ReviewerClaim | undefined
}): JSX.Element | null {
    if (!claim || !reviewer.user) {
        return null
    }
    const isMe = reviewer.user.uuid === claim.currentUserUuid
    const claimant = isClaimant(reviewer, claim)
    if (!claimant && !(isMe && claim.claimable)) {
        return null
    }

    return (
        <div className="flex shrink-0 items-center gap-1">
            {claimant && (
                <LemonTag type="success" size="small">
                    Working on it
                </LemonTag>
            )}
            {isMe && (
                <LemonButton
                    type="secondary"
                    size="xxsmall"
                    loading={claim.saving}
                    disabledReason={claim.saving ? 'Updating…' : undefined}
                    onClick={() => claim.onSetClaimed(!claimant)}
                    tooltip={claimant ? undefined : "Let your team know you're working on this report."}
                    data-attr={claimant ? 'inbox-report-unclaim' : 'inbox-report-claim'}
                >
                    {claimant ? 'Unclaim' : "I'm on it"}
                </LemonButton>
            )}
        </div>
    )
}
