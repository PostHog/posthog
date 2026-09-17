import { IconX } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'

import { EnrichedReviewer } from '../../types'
import { getReviewerDisplayName } from './reviewerDisplay'

export function SuggestedReviewerReasonGroup({
    reviewers,
    reason,
    sourceLabels,
    disabled,
    onRemove,
}: {
    reviewers: EnrichedReviewer[]
    reason: string
    sourceLabels: string[]
    disabled: boolean
    onRemove: (reviewer: EnrichedReviewer) => void
}): JSX.Element {
    return (
        <div className="rounded border bg-primary">
            <div className="flex flex-col p-1">
                {reviewers.map((reviewer) => {
                    const displayName = getReviewerDisplayName(reviewer)

                    return (
                        <div
                            key={reviewer.user?.uuid ?? reviewer.user_uuid ?? reviewer.github_login}
                            className="group/member relative flex min-w-0 items-center rounded py-0.5 pr-7 pl-1.5 hover:bg-fill-highlight"
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
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                icon={<IconX />}
                                disabledReason={disabled ? 'Updating…' : undefined}
                                onClick={() => onRemove(reviewer)}
                                tooltip={`Remove ${displayName}`}
                                className="pointer-coarse:opacity-100 absolute top-1/2 right-1 -translate-y-1/2 opacity-0 transition-opacity group-focus-within/member:opacity-100 group-hover/member:opacity-100"
                            />
                        </div>
                    )
                })}
            </div>
            <div className="flex min-w-0 items-start justify-between gap-2 border-t px-2.5 py-2">
                <span className="min-w-0 text-xs leading-snug text-tertiary [overflow-wrap:anywhere]">{reason}</span>
                <span className="flex shrink-0 flex-wrap justify-end gap-1">
                    {sourceLabels.map((sourceLabel) => (
                        <LemonTag key={sourceLabel} type="muted" size="small">
                            {sourceLabel}
                        </LemonTag>
                    ))}
                </span>
            </div>
        </div>
    )
}
