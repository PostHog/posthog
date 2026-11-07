import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { EnrichedReviewer } from '../../types'
import { isReviewerClaimant, ReviewerClaim } from './suggestedReviewers'

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
    const claimant = isReviewerClaimant(reviewer, claim)
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
