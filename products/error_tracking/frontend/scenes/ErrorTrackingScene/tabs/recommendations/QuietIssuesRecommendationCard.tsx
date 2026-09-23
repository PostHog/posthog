import { useActions } from 'kea'

import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { RecommendationCard } from './RecommendationCard'
import { recommendationsTabLogic } from './recommendationsTabLogic'
import type { QuietIssuesRecommendation } from './types'

export function QuietIssuesRecommendationCard({
    recommendation,
    dismissed,
}: {
    recommendation: QuietIssuesRecommendation
    dismissed?: boolean
}): JSX.Element | null {
    const { resolveIssue, activateIssue } = useActions(recommendationsTabLogic)

    const issues = recommendation.meta.issues ?? []
    const quietDays = recommendation.meta.quiet_days
    const total = recommendation.meta.total ?? issues.length
    const isFirstLoad = recommendation.computed_at === null
    const description = `Active issues with no exceptions in the last ${quietDays} days. Resolve them to clear your active list. They reopen by themselves if the error comes back.`

    if (isFirstLoad) {
        return (
            <RecommendationCard
                recommendationId={recommendation.id}
                title="Issues that stopped happening"
                description={description}
                dismissed={dismissed}
            />
        )
    }

    if (issues.length === 0) {
        return (
            <RecommendationCard
                recommendationId={recommendation.id}
                title="Issues that stopped happening"
                dismissed={dismissed}
            >
                <div className="text-sm text-secondary">Every active issue is still firing — nothing to clear out.</div>
            </RecommendationCard>
        )
    }

    return (
        <RecommendationCard
            recommendationId={recommendation.id}
            title="Issues that stopped happening"
            description={description}
            dismissed={dismissed}
        >
            <div className="flex flex-col gap-0">
                {issues.map((issue) => {
                    const isActive = issue.status === 'active'
                    return (
                        <div key={issue.id} className="border-b last:border-b-0">
                            <Link
                                subtle
                                to={urls.errorTrackingIssue(issue.id)}
                                className={`group flex items-center gap-3 py-2 no-underline ${
                                    isActive ? '' : 'opacity-60'
                                }`}
                            >
                                <div
                                    className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                                        isActive ? 'bg-muted' : 'bg-success'
                                    }`}
                                />
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
                                        {dayjs(issue.first_seen).fromNow(true)} old · quiet for over {quietDays} days
                                    </div>
                                </div>
                                <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                                    {isActive ? (
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            onClick={(e) => {
                                                e.preventDefault()
                                                e.stopPropagation()
                                                resolveIssue(issue.id)
                                            }}
                                        >
                                            Resolve
                                        </LemonButton>
                                    ) : (
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            onClick={(e) => {
                                                e.preventDefault()
                                                e.stopPropagation()
                                                activateIssue(issue.id)
                                            }}
                                        >
                                            Undo
                                        </LemonButton>
                                    )}
                                </div>
                            </Link>
                        </div>
                    )
                })}
            </div>
            {total > issues.length && (
                <div className="text-xs text-secondary mt-2">
                    Showing the {issues.length} oldest of {humanFriendlyLargeNumber(total)} quiet issues.
                </div>
            )}
        </RecommendationCard>
    )
}
