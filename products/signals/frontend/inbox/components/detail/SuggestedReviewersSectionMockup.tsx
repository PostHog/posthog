import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { EnrichedReviewer } from '../../types'
import { SuggestedReviewersSectionView } from './SuggestedReviewersSectionView'

export function SuggestedReviewersSectionMockup({
    suggestions,
    onAdd,
    onRemove,
}: {
    suggestions: EnrichedReviewer[]
    onAdd: () => void
    onRemove: (suggestions: EnrichedReviewer[]) => void
}): JSX.Element {
    return (
        <SuggestedReviewersSectionView
            reviewers={suggestions}
            disabled={false}
            onRemove={onRemove}
            addControl={
                <LemonButton size="small" type="secondary" icon={<IconPlus />} onClick={onAdd}>
                    Add Reviewer
                </LemonButton>
            }
        />
    )
}
