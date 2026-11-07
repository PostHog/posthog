import { Badge, Button } from '@posthog/quill'

import { EnrichedReviewer } from '../../types'
import { isReviewerClaimant, ReviewerClaim } from './suggestedReviewers'

/** The quill sibling of `SuggestedReviewerClaimControls`, for the report page behind `today-rail-nav`. */
export function QuillSuggestedReviewerClaimControls({
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
            {claimant && <Badge variant="success">Working on it</Badge>}
            {isMe && (
                <Button
                    variant="outline"
                    loading={claim.saving}
                    disabledReason={claim.saving ? 'Updating…' : undefined}
                    onClick={() => claim.onSetClaimed(!claimant)}
                    tooltip={claimant ? undefined : "Let your team know you're working on this report."}
                    data-attr={claimant ? 'inbox-report-unclaim' : 'inbox-report-claim'}
                >
                    {claimant ? 'Unclaim' : "I'm on it"}
                </Button>
            )}
        </div>
    )
}
