import { useQuery } from '@tanstack/react-query'

import { NotSignedInError } from '@/api/client'
import { queryKeys, runQuery } from '@/api/query'
import { retryUnlessMissing } from '@/api/reports'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { toError } from '@/lib/errors'
import { trendsAggregate, trendsInterval, trendsSeries } from '@/model/adapters/metric'
import { errorQuery, loadingQuery, successQuery } from '@/model/queryStates'
import type { MetricData, MetricSeries, QueryState } from '@/model/types'

/** The web serves a snapshot measured in the last 15 minutes as is, so a live result stays fresh as long. */
export const METRIC_STALE_MS = 15 * 60 * 1000

const NO_DATA: MetricData = { kind: 'none' }

type QueryData = Extract<MetricData, { kind: 'query' }>

/** Settled with no value: not loading, no error, `data` undefined. Also the shape of a disabled query. */
function noData<T>(options: { isRefetching?: boolean; refetch?: () => unknown } = {}): QueryState<T> {
    return { ...loadingQuery<T>(), isLoading: false, isRefetching: options.isRefetching ?? false, ...options }
}

// TanStack Query rejects `undefined` as query data, so "no value" travels as null and leaves as undefined.
function useLiveMetricQuery<T>(
    query: unknown,
    parse: (response: unknown) => T | undefined,
    active: boolean
): QueryState<T> {
    const scope = useProjectScope()
    const result = useQuery({
        queryKey: queryKeys.run(scope, query),
        queryFn: async ({ signal }): Promise<T | null> => parse(await runQuery(query, { signal })) ?? null,
        enabled: active && scope !== null,
        staleTime: METRIC_STALE_MS,
        retry: retryUnlessMissing,
    })
    if (!active) {
        return noData()
    }
    if (!scope) {
        return errorQuery(new NotSignedInError())
    }
    const refetch = result.refetch
    if (result.isSuccess) {
        const options = { isRefetching: result.isRefetching, refetch }
        return result.data === null ? noData(options) : successQuery(result.data, options)
    }
    if (result.isError) {
        return errorQuery(toError(result.error), refetch)
    }
    return { ...loadingQuery<T>(), refetch }
}

function useMetricData<T>(
    data: MetricData | undefined,
    enabled: boolean,
    pick: (data: QueryData) => unknown,
    parse: (response: unknown) => T | undefined,
    fromStatic: (data: Extract<MetricData, { kind: 'static' }>) => T
): QueryState<T> {
    const mode = useDataMode()
    const resolved = data ?? NO_DATA
    const query = resolved.kind === 'query' ? pick(resolved) : undefined
    const live = useLiveMetricQuery(query, parse, enabled && mode === 'live' && resolved.kind === 'query')
    switch (resolved.kind) {
        case 'static':
            return successQuery(fromStatic(resolved))
        case 'none':
            return noData()
        case 'query':
            if (mode === 'loading') {
                return loadingQuery()
            }
            // Demo views are static; a query view in demo mode has nothing to run against.
            return mode === 'demo' ? noData() : live
    }
}

/**
 * The buckets to draw. `static` data answers at once with no request. `none` (redacted, or no data) settles as a
 * success with `data` undefined, as does a query that returned no buckets. `enabled: false` leaves a query idle:
 * not loading, no data, no error.
 */
export function useMetricSeries(data: MetricData | undefined, enabled = true): QueryState<MetricSeries> {
    const interval = trendsInterval(data?.kind === 'query' ? data.seriesQuery : undefined)
    return useMetricData(
        data,
        enabled,
        (query) => query.seriesQuery,
        (response) => trendsSeries(response, interval),
        (fixture) => fixture.series
    )
}

/** The value over the whole window, as the server aggregates it. Same states as `useMetricSeries`. */
export function useMetricAggregate(data: MetricData | undefined, enabled = true): QueryState<number> {
    return useMetricData(
        data,
        enabled,
        (query) => query.aggregateQuery,
        trendsAggregate,
        (fixture) => fixture.value
    )
}
