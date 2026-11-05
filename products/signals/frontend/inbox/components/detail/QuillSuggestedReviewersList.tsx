import { useState } from 'react'

import { Button } from '@posthog/quill'

import { EnrichedReviewer, ReviewerRemoval } from '../../types'
import { QuillSuggestedReviewerPerson } from './QuillSuggestedReviewerPerson'
import { QuillSuggestedReviewerReasonGroup } from './QuillSuggestedReviewerReasonGroup'
import { buildReviewerItems, MAX_VISIBLE_SUGGESTIONS, ReviewerClaim } from './suggestedReviewers'

/** The quill sibling of `SuggestedReviewersList`, for the report page behind `today-rail-nav`. */
export function QuillSuggestedReviewersList({
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
        <div className="flex flex-col gap-1">
            {visibleItems.map((item) =>
                item.kind === 'reason-group' ? (
                    <QuillSuggestedReviewerReasonGroup
                        key={item.key}
                        reviewers={item.reviewers}
                        reason={item.reason}
                        disabled={disabled}
                        onRemove={(reviewer, removal) => onRemove([reviewer], removal)}
                        claim={claim}
                    />
                ) : (
                    <QuillSuggestedReviewerPerson
                        key={item.key}
                        reviewer={item.reviewer}
                        disabled={disabled}
                        onRemove={(removal) => onRemove([item.reviewer], removal)}
                        claim={claim}
                    />
                )
            )}
            {items.length > MAX_VISIBLE_SUGGESTIONS && (
                <Button className="w-full text-muted-foreground" onClick={() => setShowAll((visible) => !visible)}>
                    {showAll ? 'Show less' : `Show all (${items.length})`}
                </Button>
            )}
        </div>
    )
}
