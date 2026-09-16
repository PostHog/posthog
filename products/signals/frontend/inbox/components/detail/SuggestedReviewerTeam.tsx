import { IconPeople, IconX } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { EnrichedReviewer, ReviewerSuggestionGroup } from '../../types'
import { getReviewerDisplayName } from './reviewerDisplay'

export function SuggestedReviewerTeam({
    group,
    reviewers,
    sourceLabel,
    disabled,
    onRemove,
}: {
    group: ReviewerSuggestionGroup
    reviewers: EnrichedReviewer[]
    sourceLabel: string
    disabled: boolean
    onRemove: () => void
}): JSX.Element {
    const membersTooltip = (
        <div className="flex max-w-64 flex-col gap-1.5 text-left">
            <span className="font-semibold">
                {reviewers.length} {reviewers.length === 1 ? 'member' : 'members'}
            </span>
            {reviewers.map((reviewer) => (
                <span key={reviewer.user?.uuid ?? reviewer.user_uuid ?? reviewer.github_login}>
                    {getReviewerDisplayName(reviewer)}
                </span>
            ))}
        </div>
    )

    return (
        <div className="group relative grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2 rounded px-1.5 py-1.5">
            <div className="flex min-w-0 flex-col gap-0.5">
                <Tooltip title={membersTooltip}>
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        icon={<IconPeople />}
                        className="w-fit underline decoration-dotted underline-offset-2"
                    >
                        {group.name}
                    </LemonButton>
                </Tooltip>
                <span className="text-xs leading-snug text-tertiary">{group.reason}</span>
            </div>
            <LemonTag type="muted" size="small">
                {sourceLabel}
            </LemonTag>
            <LemonButton
                type="tertiary"
                size="xsmall"
                icon={<IconX />}
                disabledReason={disabled ? 'Updating…' : undefined}
                onClick={onRemove}
                tooltip={`Remove ${group.name}`}
                className="pointer-coarse:opacity-100 absolute top-1/2 right-[-3.625rem] -translate-y-1/2 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100"
            />
        </div>
    )
}
