import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { EnrichedReviewer, ReviewerSuggestionGroup } from '../../types'
import { getReviewerSourceLabel, SuggestedReviewerPerson } from './SuggestedReviewerPerson'
import { SuggestedReviewerTeam } from './SuggestedReviewerTeam'

const MAX_VISIBLE_SUGGESTIONS = 5

interface ReviewerPersonItem {
    kind: 'person'
    key: string
    reviewer: EnrichedReviewer
}

interface ReviewerTeamItem {
    kind: 'team'
    key: string
    group: ReviewerSuggestionGroup
    reviewers: EnrichedReviewer[]
    sourceLabel: string
}

type ReviewerItem = ReviewerPersonItem | ReviewerTeamItem

function reviewerKey(reviewer: EnrichedReviewer): string {
    return reviewer.user?.uuid ?? reviewer.user_uuid ?? reviewer.github_login ?? getReviewerDisplayFallback(reviewer)
}

function getReviewerDisplayFallback(reviewer: EnrichedReviewer): string {
    return reviewer.github_name ?? reviewer.user?.email ?? 'unknown-reviewer'
}

function buildReviewerItems(reviewers: EnrichedReviewer[]): ReviewerItem[] {
    const items: ReviewerItem[] = []
    const teams = new Map<string, ReviewerTeamItem>()

    for (const reviewer of reviewers) {
        const group = reviewer.suggestion_group
        if (!group) {
            items.push({ kind: 'person', key: reviewerKey(reviewer), reviewer })
            continue
        }

        const sourceLabel = getReviewerSourceLabel(reviewer)
        const key = JSON.stringify([group.name, group.reason, sourceLabel])
        const existing = teams.get(key)
        if (existing) {
            existing.reviewers.push(reviewer)
        } else {
            const item: ReviewerTeamItem = { kind: 'team', key, group, reviewers: [reviewer], sourceLabel }
            teams.set(key, item)
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
        <div className="@container mr-[3.625rem] flex flex-col gap-1.5">
            {visibleItems.map((item) =>
                item.kind === 'team' ? (
                    <SuggestedReviewerTeam
                        key={item.key}
                        group={item.group}
                        reviewers={item.reviewers}
                        sourceLabel={item.sourceLabel}
                        disabled={disabled}
                        onRemove={() => onRemove(item.reviewers)}
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
