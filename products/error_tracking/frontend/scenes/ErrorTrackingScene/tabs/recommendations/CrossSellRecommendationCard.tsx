import { LemonButton } from '@posthog/lemon-ui'

import { ListRecommendationCard } from './ListRecommendationCard'
import { RecommendationCard } from './RecommendationCard'
import type { CrossSellRecommendation } from './types'
import { CROSS_SELL_PRODUCT_INFO } from './types'

export function CrossSellRecommendationCard({
    recommendation,
    dismissed,
}: {
    recommendation: CrossSellRecommendation
    dismissed?: boolean
}): JSX.Element | null {
    const products = recommendation.meta.products ?? []

    if (products.length === 0) {
        return (
            <RecommendationCard
                recommendationId={recommendation.id}
                nextRefreshAt={recommendation.next_refresh_at}
                title="Your debugging toolkit"
                description="You're already using the PostHog products that pair best with error tracking."
                dismissed={dismissed}
            />
        )
    }

    const items = products
        .map((product) => {
            const info = CROSS_SELL_PRODUCT_INFO[product.key]
            if (!info) {
                return null
            }
            return {
                key: product.key,
                enabled: product.enabled,
                name: info.name,
                reason: info.reason,
                action: (
                    <LemonButton size="xsmall" type="secondary" to={info.enable_url}>
                        Enable
                    </LemonButton>
                ),
            }
        })
        .filter((i): i is NonNullable<typeof i> => i !== null)

    return (
        <ListRecommendationCard
            recommendationId={recommendation.id}
            nextRefreshAt={recommendation.next_refresh_at}
            title="Your debugging toolkit"
            description="Complete your setup to get the full picture."
            dismissed={dismissed}
            items={items}
            progressLabel="enabled"
        />
    )
}
