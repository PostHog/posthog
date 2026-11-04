import type { QueryKey } from '@tanstack/react-query'
import type { ProjectScope } from '@/api/reports'
import { asRecord } from '@/lib/records'

export function isReadCacheKey(key: QueryKey, scope: ProjectScope): boolean {
    if (key[1] !== scope.host || key[2] !== scope.projectId) return false
    if (key[0] === 'read-inbox') return key.length === 3
    if (key[0] !== 'views') return false
    const lengths: Record<string, number> = { insight: 7, web: 5, dashboard: 6 }
    return key.length === lengths[String(key[3])]
}

export function cacheable(key: QueryKey, data: unknown, scope: ProjectScope): boolean {
    if (!isReadCacheKey(key, scope)) return false
    const value = asRecord(data)
    if (!value) return false
    if (key[0] === 'read-inbox') return Array.isArray(value.items) && typeof value.sourceUpdatedAt === 'number'
    if (key[3] === 'insight')
        return (
            ['TrendsQuery', 'FunnelsQuery', 'RetentionQuery'].includes(String(value.queryKind)) &&
            value.sqlTable === null &&
            !rawQueryPayload(value.query)
        )
    if (key[3] === 'web') return Array.isArray(value.metrics)
    return Array.isArray(asRecord(value.view)?.tiles)
}

function fields(value: Record<string, unknown>, names: readonly string[]): Record<string, unknown> {
    return Object.fromEntries(names.filter((name) => name in value).map((name) => [name, value[name]]))
}

function rawQueryPayload(value: unknown, depth = 0): boolean {
    if (depth > 16) return true
    if (Array.isArray(value)) return value.some((item) => rawQueryPayload(item, depth + 1))
    const record = asRecord(value)
    return (
        !!record &&
        (['HogQLQuery', 'ActorsQuery', 'EventsQuery', 'PersonsNode'].includes(String(record.kind)) ||
            Object.entries(record).some(
                ([name, child]) =>
                    ['response', 'results', 'actors', 'persons'].includes(name) || rawQueryPayload(child, depth + 1)
            ))
    )
}

export function projectedData(key: QueryKey, data: unknown): unknown {
    const value = asRecord(data)
    if (!value) return null
    if (key[0] === 'read-inbox')
        return {
            sourceUpdatedAt: value.sourceUpdatedAt,
            signalCounts: value.signalCounts,
            items: Array.isArray(value.items)
                ? value.items.map((item) =>
                      fields(asRecord(item) ?? {}, [
                          'id',
                          'reportId',
                          'title',
                          'sourceProduct',
                          'sourceLabel',
                          'sources',
                          'accent',
                          'createdAt',
                          'updatedAt',
                          'modelScore',
                          'reason',
                          'state',
                          'needsInput',
                          'read',
                          'agent',
                          'pullRequestUrl',
                          'pullRequestState',
                      ])
                  )
                : [],
        }
    if (key[3] === 'dashboard') {
        const view = asRecord(value.view) ?? {}
        return {
            readAt: value.readAt,
            refreshFailed: value.refreshFailed,
            restoredFromDevice: value.restoredFromDevice,
            view: {
                ...fields(view, ['id', 'name', 'description', 'savedRange', 'lastRefresh']),
                tiles: Array.isArray(view.tiles)
                    ? view.tiles.map((tile) =>
                          fields(asRecord(tile) ?? {}, [
                              'tileId',
                              'kind',
                              'insightId',
                              'shortId',
                              'name',
                              'text',
                              'usesOwnRange',
                              'ignoresRangeOverride',
                              'capabilities',
                              'kindLabel',
                              'seriesCount',
                              'hasBreakdown',
                          ])
                      )
                    : [],
            },
        }
    }
    if (key[3] === 'web')
        return fields(value, [
            'metrics',
            'resolvedRange',
            'timezone',
            'computed',
            'lastRefreshAt',
            'cacheTargetAge',
            'nextAllowedRefreshAt',
            'readAt',
            'dataReadAt',
            'refreshFailed',
            'restoredFromDevice',
        ])
    return fields(value, [
        'insightId',
        'shortId',
        'name',
        'description',
        'queryKind',
        'query',
        'resolvedRange',
        'timezone',
        'savedRange',
        'interval',
        'format',
        'value',
        'valueAt',
        'previous',
        'delta',
        'series',
        'allSeries',
        'chartKind',
        'funnel',
        'retention',
        'ranking',
        'sqlTable',
        'inProgressFrom',
        'usesOwnRange',
        'capabilities',
        'kindLabel',
        'computed',
        'createdBy',
        'createdAt',
        'lastRefreshAt',
        'cacheTargetAge',
        'nextAllowedRefreshAt',
        'readAt',
        'dataReadAt',
        'refreshFailed',
        'restoredFromDevice',
    ])
}
