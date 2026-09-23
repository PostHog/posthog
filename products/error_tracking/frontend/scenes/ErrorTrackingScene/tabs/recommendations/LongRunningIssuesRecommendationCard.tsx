import { useActions } from 'kea'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { IssueRecommendationRow } from './IssueRecommendationRow'
import { RecommendationCard } from './RecommendationCard'
import { recommendationsTabLogic } from './recommendationsTabLogic'
import type { LongRunningIssuesRecommendation } from './types'

const TITLE = 'Long-running issues'
const DESCRIPTION = 'Your oldest active issues that are still firing this week — worth a second look.'

export function LongRunningIssuesRecommendationCard({
    recommendation,
    dismissed,
}: {
    recommendation: LongRunningIssuesRecommendation
    dismissed?: boolean
}): JSX.Element | null {
    const { suppressIssue, activateIssue } = useActions(recommendationsTabLogic)

    const issues = recommendation.meta.issues ?? []
    const isFirstLoad = recommendation.computed_at === null

    if (isFirstLoad) {
        return (
            <RecommendationCard
                recommendationId={recommendation.id}
                title={TITLE}
                description={DESCRIPTION}
                dismissed={dismissed}
            />
        )
    }

    if (issues.length === 0) {
        return (
            <RecommendationCard recommendationId={recommendation.id} title={TITLE} dismissed={dismissed}>
                <div className="text-sm text-secondary">No long-running issues right now — nice work!</div>
            </RecommendationCard>
        )
    }

    return (
        <RecommendationCard
            recommendationId={recommendation.id}
            title={TITLE}
            description={DESCRIPTION}
            dismissed={dismissed}
        >
            <div className="flex flex-col gap-0">
                {issues.map((issue) => (
                    <IssueRecommendationRow
                        key={issue.id}
                        id={issue.id}
                        name={issue.name}
                        status={issue.status}
                        subtitle={`${dayjs(issue.created_at).fromNow(true)} old · ${humanFriendlyLargeNumber(
                            issue.occurrences
                        )} occurrences in last 7 days`}
                        actionLabel="Suppress"
                        actionIsDanger
                        onAction={() => suppressIssue(issue.id)}
                        onUndo={() => activateIssue(issue.id)}
                    />
                ))}
            </div>
        </RecommendationCard>
    )
}
