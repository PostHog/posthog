import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import { HogFunctionSubTemplateIdType } from '~/types'

export type ErrorTrackingRecommendationType = 'alerts' | 'long_running_issues'

export interface ErrorTrackingRecommendation<TMeta extends Record<string, unknown> = Record<string, unknown>> {
    id: string
    type: ErrorTrackingRecommendationType
    meta: TMeta
    completed: boolean
    computed_at: string | null
    dismissed_at: string | null
    created_at: string
    updated_at: string
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

export interface LongRunningIssueItem {
    id: string
    name: string
    description: string | null
    created_at: string
    occurrences: number
    status: ErrorTrackingIssue['status']
}

export interface LongRunningIssuesRecommendationMeta extends Record<string, unknown> {
    issues: LongRunningIssueItem[]
}

export type LongRunningIssuesRecommendation = ErrorTrackingRecommendation<LongRunningIssuesRecommendationMeta>
