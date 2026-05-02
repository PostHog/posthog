import { HogFunctionSubTemplateIdType } from '~/types'

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

export interface AlertRecommendationItem {
    key: HogFunctionSubTemplateIdType
    enabled: boolean
}

export interface AlertsRecommendationMeta extends Record<string, unknown> {
    alerts: AlertRecommendationItem[]
}

export type AlertsRecommendation = ErrorTrackingRecommendation<AlertsRecommendationMeta>

export interface AlertRecommendationInfo {
    name: string
    reason: string
}

export const ALERT_RECOMMENDATION_INFO: Record<string, AlertRecommendationInfo> = {
    'error-tracking-issue-created': {
        name: 'Issue created',
        reason: 'Get notified when a new error issue is detected.',
    },
    'error-tracking-issue-reopened': {
        name: 'Issue reopened',
        reason: 'Get notified when a previously resolved issue comes back.',
    },
    'error-tracking-issue-spiking': {
        name: 'Issue spiking',
        reason: 'Get notified when an issue starts occurring more frequently than usual.',
    },
}
