export type ErrorTrackingRecommendationType = 'cross_sell'

export interface ErrorTrackingRecommendationRun<TMeta extends Record<string, unknown> = Record<string, unknown>> {
    id: string
    type: ErrorTrackingRecommendationType
    meta: TMeta
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

export type CrossSellRecommendationRun = ErrorTrackingRecommendationRun<CrossSellRecommendationMeta>

export interface ErrorTrackingRecommendationSettingsResponse {
    id: string
    ignored_recommendation_types: ErrorTrackingRecommendationType[]
}
