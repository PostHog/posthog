import type { ReactNode } from 'react'

import { IconInfo, IconPeople } from '@posthog/icons'
import { Spinner, Tooltip } from '@posthog/lemon-ui'

import { EnrichedReviewer, ReviewerRemoval } from '../../types'
import { DetailSection } from './DetailSection'
import { ReviewerClaim } from './SuggestedReviewerClaimControls'
import { SuggestedReviewersList } from './SuggestedReviewersList'

export function SuggestedReviewersSectionView({
    reviewers,
    disabled,
    onRemove,
    addControl,
    claim,
}: {
    reviewers: EnrichedReviewer[]
    disabled: boolean
    onRemove: (reviewers: EnrichedReviewer[], removal?: ReviewerRemoval) => void
    addControl: ReactNode
    claim?: ReviewerClaim
}): JSX.Element {
    return (
        <DetailSection
            icon={<IconPeople />}
            title="Suggested reviewers"
            collapsible
            afterTitle={
                <Tooltip title="PostHog uses these suggestions to route the report. Add reviewers on the pull request to request a GitHub review.">
                    {/* The header is the collapse toggle, so a click on the icon must not collapse the section. */}
                    <span
                        className="flex cursor-help items-center text-sm text-tertiary"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <IconInfo />
                    </span>
                </Tooltip>
            }
        >
            {reviewers.length === 0 ? (
                <p className="m-0 text-xs text-tertiary">No suggested reviewers yet.</p>
            ) : (
                <SuggestedReviewersList reviewers={reviewers} disabled={disabled} onRemove={onRemove} claim={claim} />
            )}
            <div className="mt-3 flex items-center justify-end gap-2">
                {disabled && <Spinner className="size-3" />}
                {addControl}
            </div>
        </DetailSection>
    )
}
