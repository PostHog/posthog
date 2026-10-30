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
import { getReviewerSourceLabel, isScoutReviewer } from './SuggestedReviewerPerson'
import { SuggestedReviewerScoutTag } from './SuggestedReviewerScoutTag'

export function SuggestedReviewerReasonGroup({
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
    const scoutNames = new Set<string>()
    const otherSourceLabels = new Set<string>()
    for (const reviewer of reviewers) {
        const sourceLabel = getReviewerSourceLabel(reviewer)
        if (isScoutReviewer(reviewer)) {
            scoutNames.add(sourceLabel)
        } else if (sourceLabel !== 'Added by teammate' || !reason.startsWith('Added by ')) {
            otherSourceLabels.add(sourceLabel)
        }
    }

    return (
        <div className="min-w-0 py-1">
            <div className="flow-root min-w-0">
                <div className="float-right ml-2 flex min-w-0 flex-wrap justify-end gap-1">
                    {scoutNames.size > 0 && <SuggestedReviewerScoutTag scoutNames={[...scoutNames]} />}
                    {[...otherSourceLabels].map((sourceLabel) => (
                        <LemonTag key={sourceLabel} type="muted" size="small" wrap className="max-w-32">
                            {sourceLabel}
                        </LemonTag>
                    ))}
                </div>
                <p className="m-0 min-w-0 break-words text-xs leading-snug text-tertiary [overflow-wrap:anywhere]">
                    {reason}
                </p>
            </div>
            <div className="mt-1 flex flex-col pl-3">
                {reviewers.map((reviewer) => {
                    const displayName = getReviewerDisplayName(reviewer)

                    return (
                        <div
                            key={reviewer.user?.uuid ?? reviewer.user_uuid ?? reviewer.github_login}
                            className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 py-0.5"
                        >
                            <ReviewerRowMenu
                                reviewer={reviewer}
                                displayName={displayName}
                                disabledReason={
                                    reviewerClaimRemoveDisabledReason(reviewer, claim, displayName) ??
                                    (disabled ? 'Updating…' : undefined)
                                }
                                onRemove={(removal) => onRemove(reviewer, removal)}
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
                            <SuggestedReviewerClaimControls reviewer={reviewer} claim={claim} />
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
