import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { EnrichedReviewer } from '../../types'
import {
    getReviewerExplanation,
    getReviewerSourceLabel,
    isScoutReviewer,
    SuggestedReviewerPerson,
} from './SuggestedReviewerPerson'
import { SuggestedReviewerReasonGroup } from './SuggestedReviewerReasonGroup'

const MAX_VISIBLE_SUGGESTIONS = 5

interface ReviewerPersonItem {
    kind: 'person'
    key: string
    reviewer: EnrichedReviewer
}

interface ReviewerReasonGroupItem {
    kind: 'reason-group'
    key: string
    reason: string
    reviewers: EnrichedReviewer[]
}

type ReviewerItem = ReviewerPersonItem | ReviewerReasonGroupItem

function reviewerKey(reviewer: EnrichedReviewer): string {
    return reviewer.user?.uuid ?? reviewer.user_uuid ?? reviewer.github_login ?? getReviewerDisplayFallback(reviewer)
}

function getReviewerDisplayFallback(reviewer: EnrichedReviewer): string {
    return reviewer.github_name ?? reviewer.user?.email ?? 'unknown-reviewer'
}

function reviewerReasonGroupKey(reviewer: EnrichedReviewer, reason: string): string {
    const isScout = isScoutReviewer(reviewer)
    return JSON.stringify([
        'reason-group',
        reason,
        isScout ? 'scout' : 'other',
        isScout ? null : getReviewerSourceLabel(reviewer),
    ])
}

export function buildReviewerItems(reviewers: EnrichedReviewer[]): ReviewerItem[] {
    const items: ReviewerItem[] = []
    const reasonCounts = new Map<string, number>()
    const reasonGroups = new Map<string, ReviewerReasonGroupItem>()

    for (const reviewer of reviewers) {
        const reason = getReviewerExplanation(reviewer)
        if (reason) {
            const groupKey = reviewerReasonGroupKey(reviewer, reason)
            reasonCounts.set(groupKey, (reasonCounts.get(groupKey) ?? 0) + 1)
        }
    }

    for (const reviewer of reviewers) {
        const reason = getReviewerExplanation(reviewer)
        const groupKey = reason ? reviewerReasonGroupKey(reviewer, reason) : null
        if (!reason || !groupKey || reasonCounts.get(groupKey) === 1) {
            items.push({ kind: 'person', key: reviewerKey(reviewer), reviewer })
            continue
        }

        const existing = reasonGroups.get(groupKey)
        if (existing) {
            existing.reviewers.push(reviewer)
        } else {
            const item: ReviewerReasonGroupItem = {
                kind: 'reason-group',
                key: groupKey,
                reason,
                reviewers: [reviewer],
            }
            reasonGroups.set(groupKey, item)
            items.push(item)
        }
    }

    return items
}

export function SuggestedReviewersList({
    reviewers,
    disabled,
    onRemove,
}: {
    reviewers: EnrichedReviewer[]
    disabled: boolean
    onRemove: (reviewers: EnrichedReviewer[]) => void
}): JSX.Element {
    const [showAll, setShowAll] = useState(false)
    const items = buildReviewerItems(reviewers)
    const visibleItems = showAll ? items : items.slice(0, MAX_VISIBLE_SUGGESTIONS)

    return (
        <div className="@container flex flex-col gap-1.5">
            {visibleItems.map((item) =>
                item.kind === 'reason-group' ? (
                    <SuggestedReviewerReasonGroup
                        key={item.key}
                        reviewers={item.reviewers}
                        reason={item.reason}
                        disabled={disabled}
                        onRemove={(reviewer) => onRemove([reviewer])}
                    />
                ) : (
                    <SuggestedReviewerPerson
                        key={item.key}
                        reviewer={item.reviewer}
                        disabled={disabled}
                        onRemove={() => onRemove([item.reviewer])}
                    />
                )
            )}
            {items.length > MAX_VISIBLE_SUGGESTIONS && (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    fullWidth
                    onClick={() => setShowAll((visible) => !visible)}
                    className="text-tertiary"
                >
                    {showAll ? 'Show less' : `Show all (${items.length})`}
                </LemonButton>
            )}
        </div>
    )
}
