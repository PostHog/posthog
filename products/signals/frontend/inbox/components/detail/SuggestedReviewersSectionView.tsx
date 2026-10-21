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
    humanControlled = false,
}: {
    reviewers: EnrichedReviewer[]
    disabled: boolean
    onRemove: (reviewers: EnrichedReviewer[]) => void
    addControl: ReactNode
    humanControlled?: boolean
}): JSX.Element {
    return (
        <DetailSection icon={<IconPeople />} title="Suggested reviewers" collapsible>
            {reviewers.length === 0 ? (
                <p className="m-0 text-xs text-tertiary">
                    {humanControlled ? 'No reviewers selected.' : 'No suggested reviewers yet.'}
                </p>
            ) : (
                <SuggestedReviewersList reviewers={reviewers} disabled={disabled} onRemove={onRemove} />
            )}
            {humanControlled && (
                <p className="mt-3 mb-0 text-xs text-secondary">
                    A person set this list. Research and scouts cannot replace it.
                </p>
            )}
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                <Tooltip title="PostHog uses these suggestions to route the report. Add reviewers on the pull request to request a GitHub review.">
                    <span className="flex cursor-help items-center text-base text-tertiary">
                        <IconInfo />
                    </span>
                </Tooltip>
                <div className="flex flex-wrap items-center gap-2">
                    {disabled && <Spinner className="size-3" />}
                    {addControl}
                </div>
            </div>
        </DetailSection>
    )
}
