export type ErrorTrackingRecommendationType = 'cross_sell' | 'alerts'

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

export interface AlertItem {
    key: string
    enabled: boolean
}

export interface AlertsRecommendationMeta extends Record<string, unknown> {
    alerts: AlertItem[]
}

export type AlertsRecommendation = ErrorTrackingRecommendation<AlertsRecommendationMeta>

export interface AlertInfo {
    name: string
    enable_url: string
    reason: string
}

const ALERTING_URL = '/error_tracking/configuration?tab=error-tracking-alerting'

export const ALERT_INFO: Record<string, AlertInfo> = {
    issue_created: {
        name: 'Issue created',
        enable_url: ALERTING_URL,
        reason: 'Get notified the moment a new error issue is detected.',
    },
    issue_reopened: {
        name: 'Issue reopened',
        enable_url: ALERTING_URL,
        reason: 'Hear about regressions when a resolved issue comes back.',
    },
    issue_spiking: {
        name: 'Issue spiking',
        enable_url: ALERTING_URL,
        reason: 'Catch incidents when an issue starts firing more than usual.',
    },
}
