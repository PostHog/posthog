import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import type { CrossSellRecommendationRun } from './types'

export function CrossSellRecommendationCard({
    recommendation,
}: {
    recommendation: CrossSellRecommendationRun
}): JSX.Element | null {
    const products = recommendation.meta.products ?? []

    if (products.length === 0) {
        return (
            <div className="border rounded-lg bg-surface-primary p-4">
                <h3 className="font-semibold text-sm m-0">Supercharge error tracking</h3>
                <p className="text-xs text-secondary mt-1 mb-0">
                    You're already using the PostHog products that pair best with error tracking.
                </p>
            </div>
        )
    }

    return (
        <div className="border rounded-lg bg-surface-primary p-4">
            <h3 className="font-semibold text-sm m-0">Supercharge error tracking</h3>
            <p className="text-xs text-secondary mt-1 mb-3">
                These PostHog products pair nicely with error tracking. Turn them on to debug faster.
            </p>
            <ul className="list-none p-0 m-0 flex flex-col gap-2">
                {products.map((product) => (
                    <li
                        key={product.key}
                        className="flex items-center justify-between gap-2 border-t border-primary pt-2 first:border-t-0 first:pt-0"
                    >
                        <span className="text-sm font-medium">{product.name}</span>
                        <div className="flex items-center gap-1">
                            <LemonButton size="xsmall" type="primary" to={product.enable_url}>
                                Enable
                            </LemonButton>
                            <Tooltip title={product.reason}>
                                <LemonButton size="xsmall" type="tertiary">
                                    Why?
                                </LemonButton>
                            </Tooltip>
                        </div>
                    </li>
                ))}
            </ul>
        </div>
    )
}
