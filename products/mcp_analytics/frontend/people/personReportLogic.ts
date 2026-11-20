import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import {
    buildBucketKeys,
    buildComparisonWindow,
    lastBucketIsInProgress,
    normalizeBucket,
    resolveInterval,
} from 'lib/utils/timeBuckets'
import { teamLogic } from 'scenes/teamLogic'

import { IntervalType } from '~/types'

import { type MCPSharedQueryFilters, mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import { type ExampleCall, toExampleCalls } from '../tool-quality/toolReportQueries'
import {
    type PersonTopDimension,
    personRecentCallsQuery,
    personSeriesQuery,
    personTopQuery,
    personTotalsQuery,
} from './peopleQueries'

export interface PersonReportLogicProps {
    distinctId: string
    dateFrom: string | null
    dateTo: string | null
}

export interface PersonTotals {
    calls: number
    sessions: number
    errors: number
    p95Ms: number
}

export interface PersonSeries {
    labels: string[]
    calls: number[]
    sessions: number[]
    errorRatePct: number[]
    p95Ms: number[]
}

export type PersonTopRows = Record<PersonTopDimension, unknown[][]>

export interface PersonRecentCall extends ExampleCall {
    isError: boolean
}

const EMPTY_TOTALS: PersonTotals = { calls: 0, sessions: 0, errors: 0, p95Ms: 0 }

function toTotals(row: unknown[] | undefined): PersonTotals {
    return row
        ? {
              calls: Number(row[1] ?? 0),
              sessions: Number(row[2] ?? 0),
              errors: Number(row[3] ?? 0),
              p95Ms: Number(row[4] ?? 0) || 0,
          }
        : EMPTY_TOTALS
}

/** One person's usage of the server: totals against the period before, a series per bucket, top usage and recent calls. */
export const personReportLogic = kea([
    path((key) => ['products', 'mcp_analytics', 'frontend', 'people', 'personReportLogic', key]),
    props({} as PersonReportLogicProps),
    key((props: PersonReportLogicProps) => `${props.distinctId}|${props.dateFrom}|${props.dateTo}`),
    connect(() => ({
        values: [mcpAnalyticsFiltersLogic, ['queryFilters as sharedQueryFilters'], teamLogic, ['timezone']],
    })),
    actions({ loadAll: true }),
    selectors({
        distinctId: [(_, p) => [p.distinctId], (distinctId: string) => distinctId],
        dateRange: [
            (_, p) => [p.dateFrom, p.dateTo],
            (dateFrom: string | null, dateTo: string | null) => ({ date_from: dateFrom, date_to: dateTo }),
        ],
        interval: [
            (s, p) => [p.dateFrom, p.dateTo, s.timezone],
            (dateFrom: string | null, dateTo: string | null, timezone: string): IntervalType =>
                resolveInterval(dateFrom, dateTo, timezone, null),
        ],
        bucketKeys: [
            (s, p) => [p.dateFrom, p.dateTo, s.timezone, s.interval],
            (dateFrom: string | null, dateTo: string | null, timezone: string, interval: IntervalType): string[] =>
                buildBucketKeys(dateFrom, dateTo, timezone, interval),
        ],
        incompleteTail: [
            (s) => [s.bucketKeys, s.timezone, s.interval],
            (bucketKeys: string[], timezone: string, interval: IntervalType): boolean =>
                lastBucketIsInProgress(bucketKeys, timezone, interval),
        ],
    }),
    loaders(({ props, values }) => ({
        totals: [
            null as { current: PersonTotals; previous: PersonTotals } | null,
            {
                loadTotals: async (_: void, breakpoint) => {
                    const window = buildComparisonWindow(props.dateFrom, props.dateTo, values.timezone, values.interval)
                    const response = await api.query(
                        personTotalsQuery(
                            props.distinctId,
                            window.currentStart,
                            { date_from: window.dateFrom, date_to: window.dateTo },
                            values.sharedQueryFilters as MCPSharedQueryFilters
                        )
                    )
                    breakpoint()
                    const rows = (response.results ?? []) as unknown[][]
                    return {
                        current: toTotals(rows.find((row) => !!row[0])),
                        previous: toTotals(rows.find((row) => !row[0])),
                    }
                },
            },
        ],
        series: [
            null as PersonSeries | null,
            {
                loadSeries: async (_: void, breakpoint) => {
                    const response = await api.query(
                        personSeriesQuery(
                            props.distinctId,
                            values.interval,
                            values.dateRange,
                            values.sharedQueryFilters as MCPSharedQueryFilters
                        )
                    )
                    breakpoint()
                    const byBucket = new Map(
                        ((response.results ?? []) as unknown[][]).map((row) => [normalizeBucket(row[0]), row])
                    )
                    const rows = values.bucketKeys.map((bucket: string) => byBucket.get(bucket))
                    const calls = rows.map((row: unknown[] | undefined) => Number(row?.[1] ?? 0))
                    return {
                        labels: values.bucketKeys,
                        calls,
                        sessions: rows.map((row: unknown[] | undefined) => Number(row?.[2] ?? 0)),
                        errorRatePct: rows.map((row: unknown[] | undefined, i: number) =>
                            calls[i] ? (Number(row?.[3] ?? 0) / calls[i]) * 100 : 0
                        ),
                        p95Ms: rows.map((row: unknown[] | undefined) => Number(row?.[4] ?? 0) || 0),
                    }
                },
            },
        ],
        topRows: [
            null as PersonTopRows | null,
            {
                loadTopRows: async (_: void, breakpoint) => {
                    const dimensions: PersonTopDimension[] = ['tools', 'harnesses', 'models']
                    const responses = await Promise.all(
                        dimensions.map((dimension) =>
                            api.query(
                                personTopQuery(
                                    props.distinctId,
                                    dimension,
                                    values.dateRange,
                                    values.sharedQueryFilters as MCPSharedQueryFilters
                                )
                            )
                        )
                    )
                    breakpoint()
                    return Object.fromEntries(
                        dimensions.map((dimension, i) => [dimension, (responses[i].results ?? []) as unknown[][]])
                    ) as PersonTopRows
                },
            },
        ],
        recentCalls: [
            [] as PersonRecentCall[],
            {
                loadRecentCalls: async (_: void, breakpoint) => {
                    const response = await api.query(
                        personRecentCallsQuery(
                            props.distinctId,
                            values.dateRange,
                            values.sharedQueryFilters as MCPSharedQueryFilters
                        )
                    )
                    breakpoint()
                    const results = (response.results ?? []) as unknown[][]
                    return toExampleCalls(results).map((call, i) => ({ ...call, isError: !!results[i][10] }))
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        loadAll: () => {
            actions.loadTotals()
            actions.loadSeries()
            actions.loadTopRows()
            actions.loadRecentCalls()
        },
    })),
    subscriptions(({ actions }) => ({
        sharedQueryFilters: (_: MCPSharedQueryFilters, previous: MCPSharedQueryFilters | undefined) => {
            if (previous) {
                actions.loadAll()
            }
        },
    })),
    afterMount(({ actions }) => actions.loadAll()),
])
