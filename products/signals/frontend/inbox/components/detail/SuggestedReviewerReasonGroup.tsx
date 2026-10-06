import { IconX } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'

import { EnrichedReviewer } from '../../types'
import { getReviewerDisplayName } from './reviewerDisplay'
import { getReviewerSourceLabel, isScoutReviewer } from './SuggestedReviewerPerson'
import { SuggestedReviewerScoutTag } from './SuggestedReviewerScoutTag'

export function SuggestedReviewerReasonGroup({
    reviewers,
    reason,
    disabled,
    onRemove,
}: {
    reviewers: EnrichedReviewer[]
    reason: string
    disabled: boolean
    onRemove: (reviewer: EnrichedReviewer) => void
}): JSX.Element {
    const scoutNames = new Set<string>()
    const otherSourceLabels = new Set<string>()
    for (const reviewer of reviewers) {
        const sourceLabel = getReviewerSourceLabel(reviewer)
        if (isScoutReviewer(reviewer)) {
            scoutNames.add(sourceLabel)
        } else {
            otherSourceLabels.add(sourceLabel)
        }
    }

    return (
        <div className="-ml-2 rounded border bg-primary">
            <div className="flex flex-col p-1">
                {reviewers.map((reviewer) => {
                    const displayName = getReviewerDisplayName(reviewer)

                    return (
                        <div
                            key={reviewer.user?.uuid ?? reviewer.user_uuid ?? reviewer.github_login}
                            className="group/member grid min-w-0 grid-cols-[minmax(0,1fr)_1.75rem] items-center gap-2 rounded py-0.5 pl-1.5 hover:bg-fill-highlight"
                        >
                            <Tooltip
                                title={
                                    reviewer.user
                                        ? undefined
                                        : 'This reviewer is not linked to a PostHog member and cannot receive the report.'
                                }
                            >
                                <span className={reviewer.user ? undefined : 'opacity-75'}>
                                    <PersonDisplay
                                        person={{ properties: { email: reviewer.user?.email, name: displayName } }}
                                        displayName={displayName}
                                        withIcon="xs"
                                        noLink
                                        noPopover
                                    />
                                </span>
                            </Tooltip>
                            <div className="flex justify-self-end">
                                <LemonButton
                                    type="tertiary"
                                    size="xsmall"
                                    icon={<IconX />}
                                    disabledReason={disabled ? 'Updating…' : undefined}
                                    onClick={() => onRemove(reviewer)}
                                    tooltip={`Remove ${displayName}`}
                                    className="pointer-coarse:opacity-100 opacity-0 transition-opacity group-focus-within/member:opacity-100 group-hover/member:opacity-100"
                                />
                            </div>
                        </div>
                    )
                })}
            </div>
            <div className="flow-root min-w-0 border-t px-2.5 py-2">
                <span className="float-right ml-2 flex min-w-0 flex-wrap justify-end gap-1">
                    {scoutNames.size > 0 && <SuggestedReviewerScoutTag scoutNames={[...scoutNames]} />}
                    {[...otherSourceLabels].map((sourceLabel) => (
                        <LemonTag key={sourceLabel} type="muted" size="small" wrap className="max-w-32">
                            {sourceLabel}
                        </LemonTag>
                    ))}
                </span>
                <span className="min-w-0 text-xs leading-snug text-tertiary [overflow-wrap:anywhere]">{reason}</span>
            </div>
        </div>
    )
}
