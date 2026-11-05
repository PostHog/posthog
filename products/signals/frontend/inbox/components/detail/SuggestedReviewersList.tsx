import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { EnrichedReviewer, ReviewerRemoval } from '../../types'
import { SuggestedReviewerPerson } from './SuggestedReviewerPerson'
import { SuggestedReviewerReasonGroup } from './SuggestedReviewerReasonGroup'
import { buildReviewerItems, MAX_VISIBLE_SUGGESTIONS, ReviewerClaim } from './suggestedReviewers'

export function SuggestedReviewersList({
    reviewers,
    disabled,
    onRemove,
    claim,
}: {
    reviewers: EnrichedReviewer[]
    disabled: boolean
    onRemove: (reviewers: EnrichedReviewer[], removal?: ReviewerRemoval) => void
    claim?: ReviewerClaim
}): JSX.Element {
    const [showAll, setShowAll] = useState(false)
    const items = buildReviewerItems(reviewers)
    const visibleItems = showAll ? items : items.slice(0, MAX_VISIBLE_SUGGESTIONS)

    return (
        <div className="@container flex flex-col gap-1.5">
            {visibleItems.map((item) =>
                item.kind === 'reason-group' ? (
                    <SuggestedReviewerReasonGroup
                        key={item.key}
                        reviewers={item.reviewers}
                        reason={item.reason}
                        disabled={disabled}
                        onRemove={(reviewer, removal) => onRemove([reviewer], removal)}
                        claim={claim}
                    />
                ) : (
                    <SuggestedReviewerPerson
                        key={item.key}
                        reviewer={item.reviewer}
                        disabled={disabled}
                        onRemove={(removal) => onRemove([item.reviewer], removal)}
                        claim={claim}
                    />
                )
            )}
            {items.length > MAX_VISIBLE_SUGGESTIONS && (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    fullWidth
                    onClick={() => setShowAll((visible) => !visible)}
                    className="text-tertiary"
                >
                    {showAll ? 'Show less' : `Show all (${items.length})`}
                </LemonButton>
            )}
        </div>
    )
}
