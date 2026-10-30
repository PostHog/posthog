import type { ActorsResponseApi } from '@/api/actors'
import type { WebOverviewItemApi, WebOverviewResponseApi } from '@/api/webAnalytics'
import { asRecord, isRecord } from '@/lib/records'

import type { MetricFormat } from '../types'
import type { ActorRow, WebOverviewMetric, WebOverviewSnapshot } from '../views'
import { hasGoodResult } from './insightSnapshot'

const METRIC_LABELS: Record<string, string> = {
    visitors: 'Visitors',
    views: 'Page views',
    sessions: 'Sessions',
    'session duration': 'Session duration',
    'bounce rate': 'Bounce rate',
    revenue: 'Revenue',
    'conversion rate': 'Conversion rate',
    'total conversions': 'Conversions',
    'unique conversions': 'Unique conversions',
    lcp_score: 'LCP score',
}

function formatFor(kind: string): MetricFormat {
    switch (kind) {
        case 'duration_s':
            return { valueFormat: 'duration', unit: 's' }
        case 'percentage':
            return { valueFormat: 'percentage', unit: null }
        case 'currency':
            return { valueFormat: 'currency', unit: null }
        default:
            return { valueFormat: 'number', unit: null }
    }
}

function finiteOrNull(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function metricOf(item: WebOverviewItemApi): WebOverviewMetric {
    const label = METRIC_LABELS[item.key] ?? item.key.charAt(0).toUpperCase() + item.key.slice(1)
    return {
        key: item.key,
        label,
        format: formatFor(item.kind),
        value: finiteOrNull(item.value),
        previous: finiteOrNull(item.previous),
        changePercent: finiteOrNull(item.changeFromPreviousPct),
        isIncreaseBad: item.isIncreaseBad === true,
    }
}

/** Same freshness rule as an insight: data and refresh fields only from a response with results and no error. */
export function webOverviewSnapshot(
    response: WebOverviewResponseApi,
    previous: WebOverviewSnapshot | undefined,
    readAt: number
): WebOverviewSnapshot {
    if (!hasGoodResult(response)) {
        const failed = Boolean(response.query_status?.error)
        if (previous) {
            return { ...previous, readAt, refreshFailed: failed || previous.refreshFailed }
        }
        return {
            metrics: [],
            resolvedRange: null,
            timezone: response.timezone ?? null,
            computed: false,
            lastRefreshAt: null,
            cacheTargetAge: null,
            nextAllowedRefreshAt: null,
            readAt,
            refreshFailed: failed,
        }
    }
    const range = response.resolved_date_range
    return {
        metrics: (response.results ?? []).map(metricOf),
        resolvedRange: range?.date_from && range.date_to ? { from: range.date_from, to: range.date_to } : null,
        timezone: response.timezone ?? null,
        computed: response.is_cached === false,
        lastRefreshAt: response.last_refresh ?? null,
        cacheTargetAge: response.cache_target_age ?? null,
        nextAllowedRefreshAt: response.next_allowed_client_refresh ?? null,
        readAt,
        refreshFailed: false,
    }
}

function actorName(actor: Record<string, unknown> | undefined): string {
    const properties = asRecord(actor?.properties)
    for (const key of ['email', 'name', '$name']) {
        const value = properties?.[key]
        if (typeof value === 'string' && value.trim()) {
            return value.trim()
        }
    }
    const distinctIds = actor?.distinct_ids
    const first = Array.isArray(distinctIds) ? distinctIds[0] : undefined
    return typeof first === 'string' && first ? first : 'Anonymous person'
}

/** People rows in `select` order. Recordings come from the second column when the query asked for them. */
export function actorsFromResponse(response: ActorsResponseApi): ActorRow[] {
    return (response.results ?? []).flatMap((row, index): ActorRow[] => {
        const actor = asRecord(row[0])
        if (!actor) {
            return []
        }
        const recordings = Array.isArray(row[1])
            ? row[1]
                  .filter(isRecord)
                  .flatMap((entry) => (typeof entry.session_id === 'string' ? [entry.session_id] : []))
            : []
        return [{ id: typeof actor.id === 'string' ? actor.id : String(index), name: actorName(actor), recordings }]
    })
}
