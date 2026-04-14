export type ErrorTrackingRecommendationType = 'cross_sell'

export interface ErrorTrackingRecommendation<TMeta extends Record<string, unknown> = Record<string, unknown>> {
    id: string
    type: ErrorTrackingRecommendationType
    meta: TMeta
    computed_at: string | null
    dismissed_at: string | null
    next_refresh_at: string | null
    created_at: string
    updated_at: string
}

export interface CrossSellProduct {
    key: string
    enabled: boolean
}

export interface CrossSellRecommendationMeta extends Record<string, unknown> {
    products: CrossSellProduct[]
}

export type CrossSellRecommendation = ErrorTrackingRecommendation<CrossSellRecommendationMeta>

export interface CrossSellProductInfo {
    name: string
    enable_url: string
    reason: string
}

export const CROSS_SELL_PRODUCT_INFO: Record<string, CrossSellProductInfo> = {
    session_replay: {
        name: 'Session replay',
        enable_url: '/replay/home',
        reason: 'See what the user did right before the error happened.',
    },
    logs: {
        name: 'Logs',
        enable_url: '/logs',
        reason: 'Jump straight to application output around the failure.',
    },
}
