import { IconX } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'

import { EnrichedReviewer } from '../../types'
import { getReviewerDisplayName } from './reviewerDisplay'

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
    const explanation = getReviewerExplanation(reviewer)
    const sourceLabel = getReviewerSourceLabel(reviewer)

    return (
        <div className="group relative grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2 rounded px-1.5 py-1.5">
            <div className={`flex min-w-0 flex-col gap-0.5 ${reviewer.user ? '' : 'opacity-75'}`}>
                <PersonDisplay
                    person={{ properties: { email: reviewer.user?.email, name: displayName } }}
                    displayName={displayName}
                    withIcon="xs"
                    noLink
                    noPopover
                />
                {explanation && <span className="text-xs leading-snug text-tertiary">{explanation}</span>}
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
                tooltip={`Remove ${displayName}`}
                className="pointer-coarse:opacity-100 absolute top-1/2 right-[-3.625rem] -translate-y-1/2 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100"
            />
        </div>
    )
}
