import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { CrossSellRecommendationCard } from './CrossSellRecommendationCard'
import { isCrossSellRecommendation, recommendationsTabLogic } from './recommendationsTabLogic'

export function RecommendationsTab(): JSX.Element {
    const { recommendations, recommendationsLoading } = useValues(recommendationsTabLogic)

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
        <div className="columns-1 md:columns-2 xl:columns-3 gap-4">
            {recommendations.map((recommendation) => {
                if (isCrossSellRecommendation(recommendation)) {
                    return (
                        <div key={recommendation.id} className="break-inside-avoid mb-4">
                            <CrossSellRecommendationCard recommendation={recommendation} />
                        </div>
                    )
                }
                return null
            })}
        </div>
    )
}
