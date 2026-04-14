export type ErrorTrackingRecommendationType = 'cross_sell'

export interface ErrorTrackingRecommendation<TMeta extends Record<string, unknown> = Record<string, unknown>> {
    id: string
    type: ErrorTrackingRecommendationType
    meta: TMeta
    dismissed_at: string | null
    created_at: string
    updated_at: string
}

export interface CrossSellProduct {
    key: string
    name: string
    enable_url: string
    enabled: boolean
    reason: string
}

export interface CrossSellRecommendationMeta extends Record<string, unknown> {
    products: CrossSellProduct[]
}

export type CrossSellRecommendation = ErrorTrackingRecommendation<CrossSellRecommendationMeta>
