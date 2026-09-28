import { IconX } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'

import { EnrichedReviewer } from '../../types'
import { getReviewerDisplayName } from './reviewerDisplay'
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

export function SuggestedReviewerPerson({
    reviewer,
    disabled,
    onRemove,
}: {
    reviewer: EnrichedReviewer
    disabled: boolean
    onRemove: () => void
}): JSX.Element {
    const displayName = getReviewerDisplayName(reviewer)
    const sourceLabel = getReviewerSourceLabel(reviewer)

    return (
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto_auto] items-start gap-2 rounded px-1.5 py-1.5 hover:bg-fill-highlight">
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
            {isScoutReviewer(reviewer) ? (
                <SuggestedReviewerScoutTag scoutNames={[sourceLabel]} />
            ) : (
                <LemonTag type="muted" size="small" wrap className="max-w-32">
                    {sourceLabel}
                </LemonTag>
            )}
            <LemonButton
                type="tertiary"
                size="xsmall"
                icon={<IconX />}
                disabledReason={disabled ? 'Updating…' : undefined}
                onClick={onRemove}
                tooltip={`Remove ${displayName}`}
            />
        </div>
    )
}
