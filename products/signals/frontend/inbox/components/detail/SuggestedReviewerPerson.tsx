import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'

import { EnrichedReviewer, ReviewerRemoval } from '../../types'
import { getReviewerDisplayName } from './reviewerDisplay'
import { ReviewerRowMenu } from './ReviewerRowMenu'
import {
    ReviewerClaim,
    reviewerClaimRemoveDisabledReason,
    SuggestedReviewerClaimControls,
} from './SuggestedReviewerClaimControls'
import { SuggestedReviewerScoutTag } from './SuggestedReviewerScoutTag'

const OTHER_SOURCE_LABELS = new Set(['Code history', 'Added by teammate', 'Agent suggestion'])

export function getReviewerSourceLabel(reviewer: EnrichedReviewer): string {
    if (reviewer.source_label) {
        return reviewer.source_label
    }
    if (reviewer.relevant_commits.length > 0) {
        return 'Code history'
    }
    if (reviewer.reason?.startsWith('Added as a reviewer by ')) {
        return 'Added by teammate'
    }
    return 'Agent suggestion'
}

export function isScoutReviewer(reviewer: EnrichedReviewer): boolean {
    if (reviewer.source_skill !== undefined) {
        return Boolean(reviewer.source_skill && reviewer.relevant_commits.length === 0)
    }
    return !OTHER_SOURCE_LABELS.has(getReviewerSourceLabel(reviewer))
}

export function getReviewerExplanation(reviewer: EnrichedReviewer): string | null {
    if ('explanation' in reviewer) {
        return reviewer.explanation ?? null
    }
    return reviewer.reason ?? reviewer.relevant_commits[0]?.reason ?? null
}

function ReviewerSourceTag({ reviewer, reason }: { reviewer: EnrichedReviewer; reason?: string }): JSX.Element {
    const sourceLabel = getReviewerSourceLabel(reviewer)
    if (isScoutReviewer(reviewer)) {
        return <SuggestedReviewerScoutTag scoutName={sourceLabel} reason={reason} />
    }
    // A manual addition's reason already names the teammate, so it replaces the generic label.
    const reasonIsLabel = !!reason && sourceLabel === 'Added by teammate' && reason.startsWith('Added by ')
    if (!reason || reasonIsLabel) {
        return (
            <LemonTag type="muted" size="small" wrap className="max-w-32">
                {reasonIsLabel ? reason : sourceLabel}
            </LemonTag>
        )
    }
    // The tag is a div, so it needs a tab stop: the hover card holds the only copy of the reason.
    return (
        <Tooltip title={reason} interactive openOnClick>
            <LemonTag type="muted" size="small" wrap className="max-w-32 cursor-help" tabIndex={0}>
                {sourceLabel}
            </LemonTag>
        </Tooltip>
    )
}

export function SuggestedReviewerPerson({
    reviewer,
    reason,
    disabled,
    onRemove,
    claim,
}: {
    reviewer: EnrichedReviewer
    /** The agent's reason for this reviewer, shown in a hover card on the source tag. */
    reason?: string
    disabled: boolean
    onRemove: (removal?: ReviewerRemoval) => void
    claim?: ReviewerClaim
}): JSX.Element {
    const displayName = getReviewerDisplayName(reviewer)

    return (
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 py-0.5">
            <ReviewerRowMenu
                reviewer={reviewer}
                displayName={displayName}
                disabledReason={
                    reviewerClaimRemoveDisabledReason(reviewer, claim, displayName) ??
                    (disabled ? 'Updating…' : undefined)
                }
                onRemove={onRemove}
            >
                <Tooltip
                    title={
                        reviewer.user
                            ? undefined
                            : 'This reviewer is not linked to a PostHog member and cannot receive the report.'
                    }
                >
                    <span className={`min-w-0 ${reviewer.user ? '' : 'opacity-75'}`}>
                        <PersonDisplay
                            person={{ properties: { email: reviewer.user?.email, name: displayName } }}
                            displayName={displayName}
                            withIcon="xs"
                            noLink
                            noPopover
                        />
                    </span>
                </Tooltip>
            </ReviewerRowMenu>
            <div className="flex items-center gap-2">
                <ReviewerSourceTag reviewer={reviewer} reason={reason} />
                <SuggestedReviewerClaimControls reviewer={reviewer} claim={claim} />
            </div>
        </div>
    )
}
