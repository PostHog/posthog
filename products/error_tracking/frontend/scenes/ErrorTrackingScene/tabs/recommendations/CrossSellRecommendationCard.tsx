import { useActions } from 'kea'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { recommendationsTabLogic } from './recommendationsTabLogic'
import type { CrossSellRecommendation } from './types'
import { CROSS_SELL_PRODUCT_INFO } from './types'

export function CrossSellRecommendationCard({
    recommendation,
    dismissed,
}: {
    recommendation: CrossSellRecommendation
    dismissed?: boolean
}): JSX.Element | null {
    const { dismissRecommendation, restoreRecommendation } = useActions(recommendationsTabLogic)
    const products = recommendation.meta.products ?? []

    if (products.length === 0) {
        return (
            <div className="border rounded-lg bg-surface-primary p-4">
                <h3 className="font-semibold text-sm m-0">Your debugging toolkit</h3>
                <p className="text-xs text-secondary mt-1 mb-0">
                    You're already using the PostHog products that pair best with error tracking.
                </p>
            </div>
        )
    }

    const enabledCount = products.filter((p) => p.enabled).length

    return (
        <div className="border rounded-lg bg-surface-primary p-4">
            <div className="flex items-center justify-between mb-1">
                <h3 className="font-semibold text-sm m-0">Your debugging toolkit</h3>
                <div className="flex items-center gap-2">
                    <span className="text-xs text-muted">
                        {enabledCount} / {products.length} enabled
                    </span>
                    <div className="w-20 h-1.5 bg-border rounded-full">
                        <div
                            className="h-1.5 bg-success rounded-full"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width: `${(enabledCount / products.length) * 100}%` }}
                        />
                    </div>
                    {dismissed ? (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => restoreRecommendation(recommendation.id)}
                        >
                            Restore
                        </LemonButton>
                    ) : (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconX />}
                            onClick={() => dismissRecommendation(recommendation.id)}
                            tooltip="Dismiss this recommendation"
                        />
                    )}
                </div>
            </div>
            <p className="text-xs text-secondary mt-1 mb-3">Complete your setup to get the full picture.</p>
            <div className="flex flex-col gap-0">
                {products.map((product, i) => {
                    const info = CROSS_SELL_PRODUCT_INFO[product.key]
                    if (!info) {
                        return null
                    }
                    return (
                        <div
                            key={product.key}
                            className={`flex items-center gap-3 py-2 border-b last:border-b-0 ${product.enabled ? 'opacity-60' : ''}`}
                        >
                            {product.enabled ? (
                                <div className="w-6 h-6 rounded-full bg-success-highlight text-success flex items-center justify-center shrink-0">
                                    <IconCheck className="text-xs" />
                                </div>
                            ) : (
                                <div className="w-6 h-6 rounded-full bg-primary-alt-highlight text-primary-alt flex items-center justify-center text-xs font-bold shrink-0">
                                    {i + 1}
                                </div>
                            )}
                            <div className="flex-1">
                                <span className="text-sm font-medium">{info.name}</span>
                                <p className="text-xs text-muted m-0">{info.reason}</p>
                            </div>
                            {product.enabled ? (
                                <span className="text-xs text-success font-medium">Enabled</span>
                            ) : (
                                <LemonButton size="xsmall" type="secondary" to={info.enable_url}>
                                    Enable
                                </LemonButton>
                            )}
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
