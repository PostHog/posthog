import type { InsightApi } from '@/api/insights'
import { serverNow } from '@/api/serverClock'
import { asRecord } from '@/lib/records'
import { insightSnapshot } from '@/model/adapters/insightSnapshot'
import type { InsightSnapshot } from '@/model/views'

const INSIGHT_KINDS = new Set([
    'TrendsQuery',
    'FunnelsQuery',
    'RetentionQuery',
    'PathsQuery',
    'StickinessQuery',
    'LifecycleQuery',
])

export function visualizationQuery(query: unknown): unknown {
    const node = asRecord(query)
    if (node?.kind === 'HogQLQuery') return { kind: 'DataVisualizationNode', source: node }
    if (INSIGHT_KINDS.has(String(node?.kind))) return { kind: 'InsightVizNode', source: node, showHeader: true }
    return query
}

export function visualizationSource(query: unknown): Record<string, unknown> | undefined {
    const node = asRecord(query)
    return asRecord(node?.source) ?? node
}

export function visualizationUrl(query: unknown, projectUrl: string, shortId?: string): string {
    return shortId
        ? `${projectUrl}/insights/${encodeURIComponent(shortId)}`
        : `${projectUrl}/insights/new#q=${encodeURIComponent(JSON.stringify(visualizationQuery(query)))}`
}

export function visualizationSnapshot(query: unknown, response: unknown, title?: string): InsightSnapshot {
    const body = asRecord(response) ?? {}
    const candidate = body.result ?? body.results ?? response
    const complete =
        visualizationSource(query)?.kind !== 'HogQLQuery' || (Array.isArray(body.columns) && body.columns.length > 0)
    const result = Array.isArray(candidate) && complete ? candidate : null
    const now = Date.now()
    const serverTime = serverNow()
    const insight: InsightApi = {
        id: 0,
        short_id: '',
        name: title || 'Chart',
        derived_name: null,
        query: visualizationQuery(query),
        result,
        last_refresh: result === null ? null : new Date(serverTime).toISOString(),
        cache_target_age: null,
        next_allowed_client_refresh: null,
        columns: Array.isArray(body.columns) ? (body.columns as string[]) : null,
        types: Array.isArray(body.types) ? (body.types as [string, string][]) : null,
        hasMore: body.hasMore === true,
        query_status: asRecord(body.query_status),
    }
    return insightSnapshot(insight, undefined, { readAt: now, serverNow: serverTime })
}
