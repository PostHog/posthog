import { useActions } from 'kea'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { IssueRecommendationRow } from './IssueRecommendationRow'
import { RecommendationCard } from './RecommendationCard'
import { recommendationsTabLogic } from './recommendationsTabLogic'
import type { QuietIssuesRecommendation } from './types'

const TITLE = 'Issues that stopped happening'

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
                title={TITLE}
                description={description}
                dismissed={dismissed}
            />
        )
    }

    if (issues.length === 0) {
        return (
            <RecommendationCard recommendationId={recommendation.id} title={TITLE} dismissed={dismissed}>
                <div className="text-sm text-secondary">
                    {total > 0
                        ? `${humanFriendlyLargeNumber(total)} issues have gone quiet, but no examples could be loaded. Refresh to try again.`
                        : 'Every active issue is still firing. Nothing to clear out.'}
                </div>
            </RecommendationCard>
        )
    }

    return (
        <RecommendationCard
            recommendationId={recommendation.id}
            title={TITLE}
            description={description}
            dismissed={dismissed}
        >
            <div className="flex flex-col gap-0">
                {issues.map((issue) => (
                    <IssueRecommendationRow
                        key={issue.id}
                        id={issue.id}
                        name={issue.name}
                        status={issue.status}
                        subtitle={`${dayjs(issue.first_seen).fromNow(true)} old · quiet for over ${quietDays} days`}
                        actionLabel="Resolve"
                        onAction={() => resolveIssue(issue.id)}
                        onUndo={() => activateIssue(issue.id)}
                    />
                ))}
            </div>
            {total > issues.length && (
                <div className="text-xs text-secondary mt-2">
                    Showing the {issues.length} oldest of {humanFriendlyLargeNumber(total)} quiet issues.
                </div>
            )}
        </RecommendationCard>
    )
}
