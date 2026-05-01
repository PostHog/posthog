import { useActions, useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { AlertsRecommendationCard } from './AlertsRecommendationCard'
import { CrossSellRecommendationCard } from './CrossSellRecommendationCard'
import { isAlertsRecommendation, isCrossSellRecommendation, recommendationsTabLogic } from './recommendationsTabLogic'

export function RecommendationsTab(): JSX.Element {
    const {
        recommendations,
        recommendationsLoading,
        activeRecommendations,
        ignoredRecommendations,
        dismissedExpanded,
    } = useValues(recommendationsTabLogic)
    const { toggleDismissedExpanded } = useActions(recommendationsTabLogic)

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
                    {activeRecommendations.map((recommendation) => {
                        if (isCrossSellRecommendation(recommendation)) {
                            return (
                                <div key={recommendation.id} className="break-inside-avoid mb-4">
                                    <CrossSellRecommendationCard recommendation={recommendation} />
                                </div>
                            )
                        }
                        if (isAlertsRecommendation(recommendation)) {
                            return (
                                <div key={recommendation.id} className="break-inside-avoid mb-4">
                                    <AlertsRecommendationCard recommendation={recommendation} />
                                </div>
                            )
                        }
                        return null
                    })}
                </div>
            )}

            {activeRecommendations.length === 0 && ignoredRecommendations.length > 0 && (
                <div className="border rounded-lg bg-surface-primary p-4 text-secondary text-sm">
                    No active recommendations — everything's looking good!
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
                            {ignoredRecommendations.map((recommendation) => {
                                if (isCrossSellRecommendation(recommendation)) {
                                    return (
                                        <div key={recommendation.id} className="break-inside-avoid mb-4">
                                            <CrossSellRecommendationCard recommendation={recommendation} dismissed />
                                        </div>
                                    )
                                }
                                if (isAlertsRecommendation(recommendation)) {
                                    return (
                                        <div key={recommendation.id} className="break-inside-avoid mb-4">
                                            <AlertsRecommendationCard recommendation={recommendation} dismissed />
                                        </div>
                                    )
                                }
                                return null
                            })}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
