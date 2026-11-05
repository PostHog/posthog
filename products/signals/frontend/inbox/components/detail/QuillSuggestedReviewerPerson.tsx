import { Badge } from '@posthog/quill'

import { EnrichedReviewer, ReviewerRemoval } from '../../types'
import { QuillReviewerRowMenu } from './QuillReviewerRowMenu'
import { QuillSuggestedReviewerClaimControls } from './QuillSuggestedReviewerClaimControls'
import { QuillSuggestedReviewerScoutTag } from './QuillSuggestedReviewerScoutTag'
import { getReviewerDisplayName } from './reviewerDisplay'
import {
    getReviewerSourceLabel,
    isScoutReviewer,
    ReviewerClaim,
    reviewerClaimRemoveDisabledReason,
} from './suggestedReviewers'

/** The quill sibling of `SuggestedReviewerPerson`, for the report page behind `today-rail-nav`. */
export function QuillSuggestedReviewerPerson({
    reviewer,
    disabled,
    onRemove,
    claim,
}: {
    reviewer: EnrichedReviewer
    disabled: boolean
    onRemove: (removal?: ReviewerRemoval) => void
    claim?: ReviewerClaim
}): JSX.Element {
    const displayName = getReviewerDisplayName(reviewer)
    const sourceLabel = getReviewerSourceLabel(reviewer)

    return (
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2">
            <QuillReviewerRowMenu
                reviewer={reviewer}
                displayName={displayName}
                disabledReason={
                    reviewerClaimRemoveDisabledReason(reviewer, claim, displayName) ??
                    (disabled ? 'Updating…' : undefined)
                }
                onRemove={onRemove}
            />
            <div className="flex flex-wrap items-center justify-end gap-2">
                {isScoutReviewer(reviewer) ? (
                    <QuillSuggestedReviewerScoutTag scoutNames={[sourceLabel]} />
                ) : (
                    <Badge className="max-w-32" title={sourceLabel}>
                        <span className="truncate">{sourceLabel}</span>
                    </Badge>
                )}
                <QuillSuggestedReviewerClaimControls reviewer={reviewer} claim={claim} />
            </div>
        </div>
    )
}
