import { Badge, Text } from '@posthog/quill'

import { EnrichedReviewer, ReviewerRemoval } from '../../types'
import { QuillReviewerRowMenu } from './QuillReviewerRowMenu'
import { QuillSuggestedReviewerClaimControls } from './QuillSuggestedReviewerClaimControls'
import { QuillSuggestedReviewerScoutTag } from './QuillSuggestedReviewerScoutTag'
import { getReviewerDisplayName } from './reviewerDisplay'
import { ReviewerClaim, reviewerClaimRemoveDisabledReason, reviewerReasonGroupSources } from './suggestedReviewers'

/** The quill sibling of `SuggestedReviewerReasonGroup`, for the report page behind `today-rail-nav`. */
export function QuillSuggestedReviewerReasonGroup({
    reviewers,
    reason,
    disabled,
    onRemove,
    claim,
}: {
    reviewers: EnrichedReviewer[]
    reason: string
    disabled: boolean
    onRemove: (reviewer: EnrichedReviewer, removal?: ReviewerRemoval) => void
    claim?: ReviewerClaim
}): JSX.Element {
    const { scoutNames, otherSourceLabels } = reviewerReasonGroupSources(reviewers, reason)

    return (
        <div className="flex min-w-0 flex-col gap-1 py-1">
            <div className="flow-root min-w-0">
                <div className="float-right ml-2 flex min-w-0 flex-wrap justify-end gap-1">
                    {scoutNames.length > 0 && <QuillSuggestedReviewerScoutTag scoutNames={scoutNames} />}
                    {otherSourceLabels.map((sourceLabel) => (
                        <Badge key={sourceLabel} className="max-w-32" title={sourceLabel}>
                            <span className="truncate">{sourceLabel}</span>
                        </Badge>
                    ))}
                </div>
                <Text size="xs" variant="muted" className="m-0 min-w-0 leading-snug wrap-anywhere">
                    {reason}
                </Text>
            </div>
            <div className="flex flex-col ps-3">
                {reviewers.map((reviewer) => {
                    const displayName = getReviewerDisplayName(reviewer)

                    return (
                        <div
                            key={reviewer.user?.uuid ?? reviewer.user_uuid ?? reviewer.github_login}
                            className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2"
                        >
                            <QuillReviewerRowMenu
                                reviewer={reviewer}
                                displayName={displayName}
                                disabledReason={
                                    reviewerClaimRemoveDisabledReason(reviewer, claim, displayName) ??
                                    (disabled ? 'Updating…' : undefined)
                                }
                                onRemove={(removal) => onRemove(reviewer, removal)}
                            />
                            <QuillSuggestedReviewerClaimControls reviewer={reviewer} claim={claim} />
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
