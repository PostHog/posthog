import { IconX } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { PersonDisplay } from 'products/persons/frontend/components/PersonDisplay'

import { EnrichedReviewer } from '../../types'
import { getReviewerDisplayName } from './reviewerDisplay'

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

export function SuggestedReviewerScoutTag({ scoutNames }: { scoutNames: string[] }): JSX.Element {
    // The tag is a div, so it needs a tab stop: the tooltip holds the only copy of the scout names.
    return (
        <Tooltip
            title={
                <div className="flex flex-col">
                    {scoutNames.map((scoutName) => (
                        <span key={scoutName}>{scoutName}</span>
                    ))}
                </div>
            }
        >
            <LemonTag type="muted" size="small" className="cursor-help" tabIndex={0}>
                Added by scout
            </LemonTag>
        </Tooltip>
    )
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
        <div className="group relative grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-x-2 gap-y-0.5 rounded px-1.5 py-1.5">
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
                <SuggestedReviewerScoutTag scoutNames={[sourceLabel]} />
            ) : (
                <LemonTag type="muted" size="small" wrap className="max-w-32">
                    {sourceLabel}
                </LemonTag>
            )}
            {explanation && (
                <span
                    className={`col-span-2 min-w-0 text-xs leading-snug text-tertiary [overflow-wrap:anywhere] ${reviewer.user ? '' : 'opacity-75'}`}
                >
                    {explanation}
                </span>
            )}
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
