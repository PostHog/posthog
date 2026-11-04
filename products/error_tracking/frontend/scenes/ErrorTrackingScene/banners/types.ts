import { HogFunctionSubTemplateIdType } from '~/types'

import type { ErrorTrackingRecommendationApi } from '../../../generated/api.schemas'

// The serializer types `meta` as an untyped JSON field, so each banner narrows it here.
export type RecommendationWithMeta<TType extends string, TMeta> = Omit<ErrorTrackingRecommendationApi, 'meta'> & {
    type: TType
    meta: TMeta
}

export interface AlertRecommendationItem {
    key: HogFunctionSubTemplateIdType
    enabled: boolean
}

export interface AlertsRecommendationMeta {
    alerts: AlertRecommendationItem[]
}

export type AlertsRecommendation = RecommendationWithMeta<'alerts', AlertsRecommendationMeta>

export type SourceMapsPlatform = 'javascript' | 'java' | 'native'

export interface SourceMapsPlatformStats {
    total_frames: number
    unresolved_frames: number
    unresolved_pct: number
}

export interface SourceMapsRecommendationMeta extends SourceMapsPlatformStats {
    threshold_pct: number
    min_sample_frames: number
    lookback_hours: number
    // The platform the top-level counts describe. Absent on rows computed before per-platform scoring.
    platform?: SourceMapsPlatform | null
    platforms?: Record<SourceMapsPlatform, SourceMapsPlatformStats>
}

export type SourceMapsRecommendation = RecommendationWithMeta<'source_maps', SourceMapsRecommendationMeta>

export type RateLimitKey = 'project' | 'per_issue'

export interface RateLimitRecommendationItem {
    key: RateLimitKey
    enabled: boolean
}

export interface RateLimitsRecommendationMeta {
    rate_limits: RateLimitRecommendationItem[]
}

export type RateLimitsRecommendation = RecommendationWithMeta<'rate_limits', RateLimitsRecommendationMeta>

/** Fills "alerts for ___ issues" in the alerts banner title. */
export const ALERT_TRIGGER_ADJECTIVES: Partial<Record<HogFunctionSubTemplateIdType, string>> = {
    'error-tracking-issue-created': 'new',
    'error-tracking-issue-reopened': 'reopened',
    'error-tracking-issue-spiking': 'spiking',
}
