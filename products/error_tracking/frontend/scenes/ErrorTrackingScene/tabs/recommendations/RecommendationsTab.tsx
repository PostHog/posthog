import { useActions, useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { AlertsRecommendationCard } from './AlertsRecommendationCard'
import { LongRunningIssuesRecommendationCard } from './LongRunningIssuesRecommendationCard'
import {
    isAlertsRecommendation,
    isLongRunningIssuesRecommendation,
    recommendationsTabLogic,
} from './recommendationsTabLogic'
import type { ErrorTrackingRecommendation } from './types'

function RecommendationCardForType({
    recommendation,
    dismissed,
}: {
    recommendation: ErrorTrackingRecommendation
    dismissed?: boolean
}): JSX.Element | null {
    if (isAlertsRecommendation(recommendation)) {
        return <AlertsRecommendationCard recommendation={recommendation} dismissed={dismissed} />
    }
    if (isLongRunningIssuesRecommendation(recommendation)) {
        return <LongRunningIssuesRecommendationCard recommendation={recommendation} dismissed={dismissed} />
    }
    return null
}

export function RecommendationsTab(): JSX.Element {
    const {
        recommendations,
        recommendationsLoading,
        activeRecommendations,
        completedRecommendations,
        ignoredRecommendations,
        dismissedExpanded,
        completedExpanded,
    } = useValues(recommendationsTabLogic)
    const { toggleDismissedExpanded, toggleCompletedExpanded } = useActions(recommendationsTabLogic)

    if (recommendationsLoading && recommendations.length === 0) {
        return (
            <div className="flex justify-center py-8">
                <Spinner />
            </div>
        )
    }

    if (recommendations.length === 0) {
        return (
            <div className="border rounded-lg bg-surface-primary p-4 text-secondary text-sm">
                No recommendations right now — everything's looking good!
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            {activeRecommendations.length > 0 && (
                <div className="columns-1 md:columns-2 xl:columns-3 gap-4">
                    {activeRecommendations.map((recommendation) => (
                        <div key={recommendation.id} className="break-inside-avoid mb-4">
                            <RecommendationCardForType recommendation={recommendation} />
                        </div>
                    ))}
                </div>
            )}

            {activeRecommendations.length === 0 &&
                (completedRecommendations.length > 0 || ignoredRecommendations.length > 0) && (
                    <div className="border rounded-lg bg-surface-primary p-4 text-secondary text-sm">
                        No active recommendations — everything's looking good!
                    </div>
                )}

            {completedRecommendations.length > 0 && (
                <div>
                    <button
                        type="button"
                        className="flex items-center gap-1 text-xs text-muted hover:text-primary cursor-pointer bg-transparent border-0 p-0"
                        onClick={toggleCompletedExpanded}
                        aria-expanded={completedExpanded}
                    >
                        <IconChevronRight className={`text-sm ${completedExpanded ? 'rotate-90' : ''}`} />
                        {completedRecommendations.length} completed
                    </button>
                    {completedExpanded && (
                        <div className="columns-1 md:columns-2 xl:columns-3 gap-4 mt-2 opacity-60">
                            {completedRecommendations.map((recommendation) => (
                                <div key={recommendation.id} className="break-inside-avoid mb-4">
                                    <RecommendationCardForType recommendation={recommendation} />
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {ignoredRecommendations.length > 0 && (
                <div>
                    <button
                        type="button"
                        className="flex items-center gap-1 text-xs text-muted hover:text-primary cursor-pointer bg-transparent border-0 p-0"
                        onClick={toggleDismissedExpanded}
                        aria-expanded={dismissedExpanded}
                    >
                        <IconChevronRight className={`text-sm ${dismissedExpanded ? 'rotate-90' : ''}`} />
                        {ignoredRecommendations.length} dismissed
                    </button>
                    {dismissedExpanded && (
                        <div className="columns-1 md:columns-2 xl:columns-3 gap-4 mt-2 opacity-60">
                            {ignoredRecommendations.map((recommendation) => (
                                <div key={recommendation.id} className="break-inside-avoid mb-4">
                                    <RecommendationCardForType recommendation={recommendation} dismissed />
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
