import { IconInfo, IconPeople, IconPlus } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { EnrichedReviewer } from '../../types'
import { DetailSection } from './DetailSection'
import { SuggestedReviewersList } from './SuggestedReviewersList'

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
        <DetailSection
            icon={<IconPeople />}
            title="Suggested reviewers"
            collapsible
            afterTitle={
                <Tooltip title="PostHog uses these suggestions to route the report. Add reviewers on the pull request to request a GitHub review.">
                    <span className="-m-1 flex cursor-help items-center p-1 text-base text-tertiary">
                        <IconInfo />
                    </span>
                </Tooltip>
            }
            rightSlot={
                <LemonButton size="xsmall" type="tertiary" icon={<IconPlus />} onClick={onAdd}>
                    Add
                </LemonButton>
            }
        >
            <SuggestedReviewersList reviewers={suggestions} disabled={false} onRemove={onRemove} />
        </DetailSection>
    )
}
