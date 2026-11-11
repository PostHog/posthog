import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { EnrichedReviewer, ReviewerRemoval } from '../../types'
import { SuggestedReviewersSectionView } from './SuggestedReviewersSectionView'

export function SuggestedReviewersSectionMockup({
    suggestions,
    onAdd,
    onRemove,
}: {
    suggestions: EnrichedReviewer[]
    onAdd: () => void
    onRemove: (suggestions: EnrichedReviewer[], removal?: ReviewerRemoval) => void
}): JSX.Element {
    return (
        <SuggestedReviewersSectionView
            reviewers={suggestions}
            disabled={false}
            defaultOpen
            onRemove={onRemove}
            addControl={
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconPlus />}
                    tooltip="Add reviewer"
                    aria-label="Add reviewer"
                    onClick={onAdd}
                />
            }
        />
    )
}
