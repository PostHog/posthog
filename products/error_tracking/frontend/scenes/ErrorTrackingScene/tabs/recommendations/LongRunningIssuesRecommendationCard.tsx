import { useActions } from 'kea'

import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { urls } from 'scenes/urls'

import { RecommendationCard } from './RecommendationCard'
import { recommendationsTabLogic } from './recommendationsTabLogic'
import type { LongRunningIssuesRecommendation } from './types'

export function LongRunningIssuesRecommendationCard({
    recommendation,
    dismissed,
}: {
    recommendation: LongRunningIssuesRecommendation
    dismissed?: boolean
}): JSX.Element | null {
    const { suppressIssue, activateIssue } = useActions(recommendationsTabLogic)

    const issues = recommendation.meta.issues ?? []

    if (issues.length === 0) {
        return (
            <RecommendationCard recommendationId={recommendation.id} title="Long-running issues" dismissed={dismissed}>
                <div className="text-sm text-secondary">No long-running issues right now — nice work!</div>
            </RecommendationCard>
        )
    }

    return (
        <RecommendationCard
            recommendationId={recommendation.id}
            title="Long-running issues"
            description="Your oldest active issues that are still firing this week — worth a second look."
            dismissed={dismissed}
        >
            <div className="flex flex-col gap-0">
                {issues.map((issue) => {
                    const isActive = issue.status === 'active'
                    return (
                        <Link
                            key={issue.id}
                            subtle
                            to={urls.errorTrackingIssue(issue.id)}
                            className={`group flex items-center gap-3 py-2 border-b last:border-b-0 no-underline ${
                                isActive ? '' : 'opacity-60'
                            }`}
                        >
                            <div className="flex-1 min-w-0">
                                <div className="text-sm font-medium truncate flex items-center gap-2">
                                    <span className="truncate">{issue.name}</span>
                                    {!isActive && (
                                        <LemonTag size="small" type="muted">
                                            {issue.status}
                                        </LemonTag>
                                    )}
                                </div>
                                <div className="text-xs text-secondary">
                                    {dayjs(issue.created_at).fromNow(true)} old ·{' '}
                                    {humanFriendlyLargeNumber(issue.occurrences)} occurrences in last 7 days
                                </div>
                            </div>
                            <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                                {isActive ? (
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        status="danger"
                                        onClick={(e) => {
                                            e.preventDefault()
                                            e.stopPropagation()
                                            suppressIssue({ issueId: issue.id })
                                        }}
                                    >
                                        Suppress
                                    </LemonButton>
                                ) : (
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        onClick={(e) => {
                                            e.preventDefault()
                                            e.stopPropagation()
                                            activateIssue({ issueId: issue.id })
                                        }}
                                    >
                                        Undo
                                    </LemonButton>
                                )}
                            </div>
                        </Link>
                    )
                })}
            </div>
        </RecommendationCard>
    )
}
