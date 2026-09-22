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
    const explanation = getReviewerExplanation(reviewer)
    const sourceLabel = getReviewerSourceLabel(reviewer)

    return (
        <div className="group grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-x-2 gap-y-0.5 rounded px-1.5 py-1.5">
            <div className={`min-w-0 ${reviewer.user ? '' : 'opacity-75'}`}>
                <Tooltip
                    title={
                        reviewer.user
                            ? undefined
                            : 'This reviewer is not linked to a PostHog member and cannot receive the report.'
                    }
                >
                    <span>
                        <PersonDisplay
                            person={{ properties: { email: reviewer.user?.email, name: displayName } }}
                            displayName={displayName}
                            withIcon="xs"
                            noLink
                            noPopover
                        />
                    </span>
                </Tooltip>
            </div>
            {isScoutReviewer(reviewer) ? (
                <div className="col-start-2 row-start-1 justify-self-end">
                    <SuggestedReviewerScoutTag scoutNames={[sourceLabel]} />
                </div>
            ) : (
                <div className="col-start-2 row-start-1 justify-self-end">
                    <LemonTag type="muted" size="small" wrap className="max-w-32">
                        {sourceLabel}
                    </LemonTag>
                </div>
            )}
            {explanation && (
                <span
                    className={`col-start-1 col-end-2 min-w-0 text-xs leading-snug text-tertiary [overflow-wrap:anywhere] ${reviewer.user ? '' : 'opacity-75'}`}
                >
                    {explanation}
                </span>
            )}
            <div className="col-start-2 row-start-2 flex self-center justify-self-end">
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    icon={<IconX />}
                    disabledReason={disabled ? 'Updating…' : undefined}
                    onClick={onRemove}
                    tooltip={`Remove ${displayName}`}
                    className="pointer-coarse:opacity-100 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100"
                />
            </div>
        </div>
    )
}
