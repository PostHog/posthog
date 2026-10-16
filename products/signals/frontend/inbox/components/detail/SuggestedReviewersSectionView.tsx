import type { ReactNode } from 'react'

import { IconInfo, IconPeople } from '@posthog/icons'
import { Spinner, Tooltip } from '@posthog/lemon-ui'

import { EnrichedReviewer } from '../../types'
import { DetailSection } from './DetailSection'
import { SuggestedReviewersList } from './SuggestedReviewersList'

export function SuggestedReviewersSectionView({
    reviewers,
    disabled,
    onRemove,
    addControl,
}: {
    reviewers: EnrichedReviewer[]
    disabled: boolean
    onRemove: (reviewers: EnrichedReviewer[]) => void
    addControl: ReactNode
}): JSX.Element {
    return (
        <DetailSection icon={<IconPeople />} title="Suggested reviewers" collapsible>
            {reviewers.length === 0 ? (
                <p className="m-0 text-xs text-tertiary">No suggested reviewers yet.</p>
            ) : (
                <SuggestedReviewersList reviewers={reviewers} disabled={disabled} onRemove={onRemove} />
            )}
            <div className="mt-3 flex items-center justify-between gap-2">
                <Tooltip title="PostHog uses these suggestions to route the report. Add reviewers on the pull request to request a GitHub review.">
                    <span className="flex cursor-help items-center text-base text-tertiary">
                        <IconInfo />
                    </span>
                </Tooltip>
                <div className="flex items-center gap-2">
                    {disabled && <Spinner className="size-3" />}
                    {addControl}
                </div>
            </div>
        </DetailSection>
    )
}
