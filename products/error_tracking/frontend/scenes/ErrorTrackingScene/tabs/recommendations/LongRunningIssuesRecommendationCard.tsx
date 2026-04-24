import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { RecommendationCard } from './RecommendationCard'
import type { LongRunningIssuesRecommendation } from './types'

export function LongRunningIssuesRecommendationCard({
    recommendation,
    dismissed,
}: {
    recommendation: LongRunningIssuesRecommendation
    dismissed?: boolean
}): JSX.Element | null {
    const issues = recommendation.meta.issues ?? []

    if (issues.length === 0) {
        return null
    }

    return (
        <RecommendationCard
            recommendationId={recommendation.id}
            nextRefreshAt={recommendation.next_refresh_at}
            title="Long-running issues"
            description="Your oldest active issues that are still firing this week — worth a second look."
            dismissed={dismissed}
        >
            <div className="flex flex-col gap-0">
                {issues.map((issue) => (
                    <div key={issue.id} className="flex items-center gap-3 py-2 border-b last:border-b-0">
                        <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium truncate">{issue.name}</div>
                            <div className="text-xs text-muted">{dayjs(issue.created_at).fromNow(true)} old</div>
                        </div>
                        <LemonButton size="xsmall" type="secondary" to={urls.errorTrackingIssue(issue.id)}>
                            View
                        </LemonButton>
                    </div>
                ))}
            </div>
        </RecommendationCard>
    )
}
