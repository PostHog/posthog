import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'
import { webStatsBreakdownToPropertyName } from 'scenes/web-analytics/common'
import {
    MappingTypes,
    getSourceMappingStatus,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/CampaignMapping/mappingUtils'

import {
    DateRange,
    DefaultChannelTypes,
    MarketingAnalyticsConfig,
    NativeMarketingSource,
    WebAnalyticsPropertyFilters,
    WebStatsBreakdown,
    WebStatsTableQueryResponse,
} from '~/queries/schema/schema-general'

const PAID_CHANNELS = new Set<string>([
    DefaultChannelTypes.PaidSearch,
    DefaultChannelTypes.PaidSocial,
    DefaultChannelTypes.PaidVideo,
    DefaultChannelTypes.PaidShopping,
    DefaultChannelTypes.PaidUnknown,
    DefaultChannelTypes.CrossNetwork,
    'Display',
])

const SNOOZE_DURATION_MS = 30 * 24 * 60 * 60 * 1000
const MAX_DISMISSALS = 2

export interface PaidTrafficThreshold {
    minVisitors: number
    minShare: number
}

const DEFAULT_PAID_TRAFFIC_THRESHOLD: PaidTrafficThreshold = { minVisitors: 50, minShare: 0.03 }

export interface PaidTrafficSummary {
    paidVisitors: number
    share: number
}

export interface MarketingCrossSellSnooze {
    dismissedAt: number | null
    dismissCount: number
}

interface MarketingAnalyticsDestinationParams {
    hasConnectedSources: boolean | null
    platform: NativeMarketingSource | null
    dateRange: DateRange | null | undefined
    setupEnabled: boolean
}

export function isMarketingSetupEnabled(featureFlags: FeatureFlagsSet): boolean {
    return !!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_SETUP]
}

export function isMarketingCrossSellTestArm(featureFlags: FeatureFlagsSet): boolean {
    return (
        featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_MARKETING_CROSS_SELL] === true &&
        featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_MARKETING_CROSS_SELL_V2] === 'test'
    )
}

function isPaidChannel(value: unknown): boolean {
    return typeof value === 'string' && PAID_CHANNELS.has(value)
}

function visitorsColumnIndex(response: WebStatsTableQueryResponse | null): number {
    return response?.columns?.indexOf('context.columns.visitors') ?? -1
}

function currentVisitors(row: unknown, visitorsIndex: number): number {
    if (!Array.isArray(row)) {
        return 0
    }
    const visitors = row[visitorsIndex]
    return Array.isArray(visitors) && typeof visitors[0] === 'number' ? visitors[0] : 0
}

export function summarizePaidTraffic(response: WebStatsTableQueryResponse | null): PaidTrafficSummary | null {
    const visitorsIndex = visitorsColumnIndex(response)
    if (!response || visitorsIndex < 0) {
        return null
    }
    let paidVisitors = 0
    let totalVisitors = 0
    for (const row of response.results) {
        const visitors = currentVisitors(row, visitorsIndex)
        totalVisitors += visitors
        if (Array.isArray(row) && isPaidChannel(row[0])) {
            paidVisitors += visitors
        }
    }
    return { paidVisitors, share: totalVisitors > 0 ? paidVisitors / totalVisitors : 0 }
}

export function parsePaidTrafficThreshold(payload: unknown): PaidTrafficThreshold {
    const values = typeof payload === 'object' && payload !== null ? (payload as Record<string, unknown>) : {}
    return {
        minVisitors:
            typeof values.min_visitors === 'number' ? values.min_visitors : DEFAULT_PAID_TRAFFIC_THRESHOLD.minVisitors,
        minShare: typeof values.min_share === 'number' ? values.min_share : DEFAULT_PAID_TRAFFIC_THRESHOLD.minShare,
    }
}

export function meetsPaidTrafficThreshold(
    summary: PaidTrafficSummary | null,
    threshold: PaidTrafficThreshold = DEFAULT_PAID_TRAFFIC_THRESHOLD
): boolean {
    return (
        !!summary &&
        summary.paidVisitors > 0 &&
        summary.paidVisitors >= threshold.minVisitors &&
        summary.share >= threshold.minShare
    )
}

function adPlatformForUtmSource(
    value: unknown,
    config: MarketingAnalyticsConfig | null | undefined,
    enabledSources: readonly NativeMarketingSource[]
): NativeMarketingSource | null {
    if (typeof value !== 'string') {
        return null
    }
    const status = getSourceMappingStatus(value, config ?? null)
    if (status.type === MappingTypes.Unmapped || !enabledSources.includes(status.integration)) {
        return null
    }
    return status.integration
}

export interface PaidTrafficTarget {
    platform: NativeMarketingSource | null
}

export function paidTrafficTarget(
    breakdown: WebStatsBreakdown,
    value: unknown,
    config: MarketingAnalyticsConfig | null | undefined,
    enabledSources: readonly NativeMarketingSource[]
): PaidTrafficTarget | null {
    if (breakdown === WebStatsBreakdown.InitialChannelType) {
        return isPaidChannel(value) ? { platform: null } : null
    }
    if (breakdown === WebStatsBreakdown.InitialUTMSource) {
        const platform = adPlatformForUtmSource(value, config, enabledSources)
        return platform ? { platform } : null
    }
    return null
}

const TARGET_BREAKDOWNS = [WebStatsBreakdown.InitialChannelType, WebStatsBreakdown.InitialUTMSource]

export function paidTrafficTargetFromFilters(
    filters: WebAnalyticsPropertyFilters,
    config: MarketingAnalyticsConfig | null | undefined,
    enabledSources: readonly NativeMarketingSource[]
): PaidTrafficTarget | null {
    let channelTarget: PaidTrafficTarget | null = null
    for (const filter of filters) {
        const breakdown = TARGET_BREAKDOWNS.find((candidate) => {
            const property = webStatsBreakdownToPropertyName(candidate)
            return property?.key === filter.key && property.type === filter.type
        })
        if (!breakdown || filter.operator !== 'exact') {
            continue
        }
        const values = Array.isArray(filter.value) ? filter.value : [filter.value]
        for (const value of values) {
            const target = paidTrafficTarget(breakdown, value, config, enabledSources)
            if (target?.platform) {
                return target
            }
            channelTarget = channelTarget ?? target
        }
    }
    return channelTarget
}

export function detectAdPlatforms(
    response: WebStatsTableQueryResponse | null,
    config: MarketingAnalyticsConfig | null | undefined,
    enabledSources: readonly NativeMarketingSource[]
): NativeMarketingSource[] {
    const visitorsIndex = visitorsColumnIndex(response)
    if (!response || visitorsIndex < 0) {
        return []
    }
    const visitorsByPlatform = new Map<NativeMarketingSource, number>()
    for (const row of response.results) {
        const visitors = currentVisitors(row, visitorsIndex)
        const platform = Array.isArray(row) ? adPlatformForUtmSource(row[0], config, enabledSources) : null
        if (platform && visitors > 0) {
            visitorsByPlatform.set(platform, (visitorsByPlatform.get(platform) ?? 0) + visitors)
        }
    }
    return [...visitorsByPlatform.entries()].sort((a, b) => b[1] - a[1]).map(([platform]) => platform)
}

export function snoozeAfterDismissal(snooze: MarketingCrossSellSnooze, now: number): MarketingCrossSellSnooze {
    return { dismissedAt: now, dismissCount: snooze.dismissCount + 1 }
}

export function isMarketingCrossSellSnoozed(snooze: MarketingCrossSellSnooze, now: number): boolean {
    if (snooze.dismissCount >= MAX_DISMISSALS) {
        return true
    }
    return snooze.dismissedAt !== null && now - snooze.dismissedAt < SNOOZE_DURATION_MS
}

export function buildMarketingAnalyticsDestination({
    hasConnectedSources,
    platform,
    dateRange,
    setupEnabled,
}: MarketingAnalyticsDestinationParams): string {
    const params = new URLSearchParams()
    if (dateRange) {
        if (dateRange.date_from) {
            params.set('date_from', dateRange.date_from)
        }
        // An empty value marks an open-ended range, so Marketing analytics drops a saved end date.
        params.set('date_to', dateRange.date_to ?? '')
    }
    if (hasConnectedSources === false && platform) {
        return urls.dataWarehouseSourceNew(
            platform,
            `${urls.marketingAnalyticsApp()}?${params.toString()}`,
            'Marketing analytics',
            undefined,
            'web_analytics_cross_sell'
        )
    }
    if (hasConnectedSources === false && setupEnabled) {
        params.set('tab', 'setup')
        params.set('section', 'sources')
    }
    return `${urls.marketingAnalyticsApp()}?${params.toString()}`
}
