import { IconPlug } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { RecommendationTile } from '../RecommendationTile'

export interface MissingProduct {
    key: 'logs' | 'session_replay'
    name: string
    enabled: boolean
    explanation: string
}

const PRODUCT_ICONS: Record<string, string> = {
    logs: '📋',
    session_replay: '🎬',
}

export function CrossProductTile({ products }: { products: MissingProduct[] }): JSX.Element {
    const disabledProducts = products.filter((p) => !p.enabled)

    if (disabledProducts.length === 0) {
        return <></>
    }

    return (
        <RecommendationTile
            tileId="cross-product"
            icon={<IconPlug className="text-link" />}
            title="Enhance your debugging workflow"
            category="Integrations"
            priority="setup"
        >
            <p className="text-xs text-secondary mb-2">
                Error tracking works best with other PostHog products. Enable these for a more complete picture.
            </p>
            <div className="space-y-2">
                {disabledProducts.map((product) => (
                    <div key={product.key} className="flex items-center gap-3 bg-surface-alt rounded-lg px-3 py-2.5">
                        <span className="text-lg shrink-0">{PRODUCT_ICONS[product.key]}</span>
                        <div className="flex-1 min-w-0">
                            <span className="text-sm font-medium">{product.name}</span>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                            <Tooltip title={product.explanation}>
                                <LemonButton size="xsmall" type="tertiary">
                                    Why?
                                </LemonButton>
                            </Tooltip>
                            <LemonButton size="xsmall" type="primary">
                                Enable
                            </LemonButton>
                        </div>
                    </div>
                ))}
            </div>
        </RecommendationTile>
    )
}
