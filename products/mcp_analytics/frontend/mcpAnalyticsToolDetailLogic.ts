import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateFilterToText, dateStringToDayJs, getDefaultInterval } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    DateRange,
    MCPHarnessBreakdownItem,
    MCPToolDailyStatItem,
    MCPToolDescriptionItem,
    MCPToolFailureItem,
    MCPToolNeighborItem,
    MCPToolSampleIntentItem,
    MCPToolStatsItem,
    MCPToolTopUserItem,
    NodeKind,
} from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import type { mcpAnalyticsToolDetailLogicType } from './mcpAnalyticsToolDetailLogicType'
import { buildBucketKeys, normalizeBucket } from './timeBuckets'

export interface ToolSummary {
    calls: number
    errors: number
    p50_ms: number | null
    p95_ms: number | null
    users: number
    conversations: number
}

export interface DescriptionRevision {
    description: string
    last_seen: string
}

export interface IntentCoverage {
    with_intent: number
    total: number
}

export interface DailyToolStat {
    day: string
    calls: number
    errors: number
    p50: number
    p95: number
    users: number
    sessions: number
}

export interface DailyChartData {
    labels: string[]
    calls: number[]
    errors: number[]
    p50: number[]
    p95: number[]
    users: number[]
    sessions: number[]
}

const EMPTY_CHART_DATA: DailyChartData = {
    labels: [],
    calls: [],
    errors: [],
    p50: [],
    p95: [],
    users: [],
    sessions: [],
}

export type ResultRows = unknown[][]

// Project the per-bucket rows onto the full set of interval buckets spanning the selected window
// (ClickHouse only returns buckets with data). `bucketKeys` covers the whole window at the active
// interval so the sparklines and trend charts match the chosen range — and always have enough points
// to draw a line — even when the tool has data on only a bucket or two. Counts fill with 0; latency
// fills with NaN so the chart skips the point instead of dipping to 0. Rows match by normalized
// bucket key, so day, hour, and minute intervals all line up. No rows at all keeps the empty state.
export function buildDailyChartData(rows: DailyToolStat[], bucketKeys: string[], timezone: string): DailyChartData {
    if (rows.length === 0) {
        return EMPTY_CHART_DATA
    }
    const byBucket = new Map(rows.map((r) => [normalizeBucket(r.day, timezone), r]))
    const at = bucketKeys.map((k) => byBucket.get(k))
    return {
        labels: bucketKeys,
        calls: at.map((r) => r?.calls ?? 0),
        errors: at.map((r) => r?.errors ?? 0),
        p50: at.map((r) => (r ? r.p50 : NaN)),
        p95: at.map((r) => (r ? r.p95 : NaN)),
        users: at.map((r) => r?.users ?? 0),
        sessions: at.map((r) => r?.sessions ?? 0),
    }
}

export interface MCPAnalyticsToolDetailLogicProps {
    toolName: string
}

export interface DateFilter {
    dateFrom: string | null
    dateTo: string | null
}

// The window carries over from the Tool quality tab via date_from / date_to search params
// (see mcpAnalyticsToolQualityLogic). Without them — e.g. opening a tool page directly — we
// default to the last 30 days.
const DEFAULT_DATE_FILTER: DateFilter = { dateFrom: '-30d', dateTo: null }

// Tools most often called immediately before/after this one within the same conversation.
async function neighborRows(
    toolName: string,
    direction: 'before' | 'after',
    dateRange: DateRange
): Promise<ResultRows> {
    const response = (await api.query({
        kind: NodeKind.MCPToolNeighborsQuery,
        toolName,
        neighborDirection: direction,
        dateRange,
    })) as { results?: MCPToolNeighborItem[] }
    return (response?.results ?? []).map((r) => [r.neighbor_tool, r.co_occurrences])
}

export const mcpAnalyticsToolDetailLogic = kea<mcpAnalyticsToolDetailLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'mcpAnalyticsToolDetailLogic']),
    key((props: MCPAnalyticsToolDetailLogicProps) => props.toolName),
    props({} as MCPAnalyticsToolDetailLogicProps),

    actions({
        setDateFilter: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        loadAllSections: true,
    }),

    reducers({
        dateFilter: [
            DEFAULT_DATE_FILTER,
            {
                setDateFilter: (_, { dateFrom, dateTo }): DateFilter => ({ dateFrom, dateTo }),
            },
        ],
    }),

    loaders(({ props, values }) => ({
        summary: [
            null as ToolSummary | null,
            {
                loadSummary: async (): Promise<ToolSummary | null> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPToolStatsQuery,
                        toolName: props.toolName,
                        dateRange: values.dateRange,
                    })) as { results?: MCPToolStatsItem[] }
                    const row = response?.results?.[0]
                    if (!row) {
                        return null
                    }
                    return {
                        calls: row.calls,
                        errors: row.errors,
                        p50_ms: row.p50_ms,
                        p95_ms: row.p95_ms,
                        users: row.users,
                        conversations: row.conversations,
                    }
                },
            },
        ],
        descriptions: [
            [] as DescriptionRevision[],
            {
                loadDescriptions: async (): Promise<DescriptionRevision[]> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPToolDescriptionsQuery,
                        toolName: props.toolName,
                        dateRange: values.dateRange,
                    })) as { results?: MCPToolDescriptionItem[] }
                    return (response?.results ?? []).map((r) => ({
                        description: r.description,
                        last_seen: r.last_seen,
                    }))
                },
            },
        ],
        intentCoverage: [
            null as IntentCoverage | null,
            {
                // Reads the same MCPToolStatsQuery as `summary`; the coverage denominator is the call count.
                loadIntentCoverage: async (): Promise<IntentCoverage | null> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPToolStatsQuery,
                        toolName: props.toolName,
                        dateRange: values.dateRange,
                    })) as { results?: MCPToolStatsItem[] }
                    const row = response?.results?.[0]
                    if (!row) {
                        return null
                    }
                    return { with_intent: row.with_intent, total: row.calls }
                },
            },
        ],
        dailyStats: [
            [] as DailyToolStat[],
            {
                loadDailyStats: async (): Promise<DailyToolStat[]> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPToolDailyStatsQuery,
                        toolName: props.toolName,
                        dateRange: values.dateRange,
                        interval: values.interval,
                    })) as { results?: MCPToolDailyStatItem[] }
                    return (response?.results ?? []).map((r) => ({
                        day: r.day,
                        calls: r.calls,
                        errors: r.errors,
                        p50: r.p50,
                        p95: r.p95,
                        users: r.users,
                        sessions: r.sessions,
                    }))
                },
            },
        ],
        failureRows: [
            [] as ResultRows,
            {
                loadFailureRows: async (): Promise<ResultRows> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPToolFailuresQuery,
                        toolName: props.toolName,
                        dateRange: values.dateRange,
                    })) as { results?: MCPToolFailureItem[] }
                    return (response?.results ?? []).map((r) => [r.message, r.occurrences, r.last_seen, r.harnesses])
                },
            },
        ],
        sampleIntentRows: [
            [] as ResultRows,
            {
                loadSampleIntentRows: async (): Promise<ResultRows> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPToolSampleIntentsQuery,
                        toolName: props.toolName,
                        dateRange: values.dateRange,
                    })) as { results?: MCPToolSampleIntentItem[] }
                    return (response?.results ?? []).map((r) => [r.timestamp, r.intent, r.intent_source, r.harness])
                },
            },
        ],
        neighborsBeforeRows: [
            [] as ResultRows,
            {
                loadNeighborsBeforeRows: async (): Promise<ResultRows> =>
                    neighborRows(props.toolName, 'before', values.dateRange),
            },
        ],
        neighborsAfterRows: [
            [] as ResultRows,
            {
                loadNeighborsAfterRows: async (): Promise<ResultRows> =>
                    neighborRows(props.toolName, 'after', values.dateRange),
            },
        ],
        byHarnessRows: [
            [] as ResultRows,
            {
                // Server-resolved harness labels via the same runner as the dashboard (scoped to this
                // tool's new-SDK calls by toolName), so the pill matches the dashboard's bucketing exactly.
                loadByHarnessRows: async (): Promise<ResultRows> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPHarnessBreakdownQuery,
                        toolName: props.toolName,
                        dateRange: values.dateRange,
                    })) as { results?: MCPHarnessBreakdownItem[] }
                    return (response?.results ?? []).map((r) => [
                        r.harness,
                        r.total_calls,
                        r.errors,
                        r.error_rate_pct,
                        r.sessions,
                    ])
                },
            },
        ],
        topUserRows: [
            [] as ResultRows,
            {
                // The person tuple is rebuilt into the [distinct_id, _, properties] shape renderPersonCell expects.
                loadTopUserRows: async (): Promise<ResultRows> => {
                    const response = (await api.query({
                        kind: NodeKind.MCPToolTopUsersQuery,
                        toolName: props.toolName,
                        dateRange: values.dateRange,
                    })) as { results?: MCPToolTopUserItem[] }
                    return (response?.results ?? []).map((r) => [
                        [r.distinct_id, '', r.person_properties],
                        r.calls,
                        r.errors,
                        r.error_rate_pct,
                        r.harnesses,
                        r.last_seen,
                    ])
                },
            },
        ],
    })),

    selectors({
        toolName: [() => [(_, props) => props.toolName], (toolName: string) => toolName],

        dailyChartData: [
            (s) => [s.dailyStats, s.dateFilter, s.interval, teamLogic.selectors.timezone],
            (
                dailyStats: DailyToolStat[],
                dateFilter: DateFilter,
                interval: IntervalType,
                timezone: string
            ): DailyChartData => {
                const bucketKeys = buildBucketKeys(dateFilter.dateFrom, dateFilter.dateTo, timezone, interval)
                return buildDailyChartData(dailyStats, bucketKeys, timezone)
            },
        ],

        // Grouping interval for the daily series — PostHog's standard auto-choice, matching the query's
        // dateTrunc so a sub-day window buckets by hour/minute instead of collapsing to one day point.
        interval: [
            (s) => [s.dateFilter],
            (dateFilter: DateFilter): IntervalType => getDefaultInterval(dateFilter.dateFrom, dateFilter.dateTo),
        ],

        // Resolve the `dateFilter` state (camelCase, nullable, may be relative like '-30d') into the
        // absolute snake_case `DateRange` the query API takes. Done once so every section queries the
        // exact same window — a relative '-Nd' would re-resolve per section and drift after midnight.
        dateRange: [
            (s) => [s.dateFilter, teamLogic.selectors.timezone],
            (dateFilter: DateFilter, timezone: string): DateRange => {
                const to = dateStringToDayJs(dateFilter.dateTo, timezone) ?? dayjs().tz(timezone)
                const from =
                    dateStringToDayJs(dateFilter.dateFrom, timezone) ?? dayjs().tz(timezone).subtract(30, 'day')
                return { date_from: from.toISOString(), date_to: to.toISOString() }
            },
        ],

        dateRangeLabel: [
            (s) => [s.dateFilter],
            (dateFilter: DateFilter): string =>
                dateFilterToText(dateFilter.dateFrom, dateFilter.dateTo, 'the selected range') ?? 'the selected range',
        ],
    }),

    listeners(({ actions }) => ({
        loadAllSections: () => {
            actions.loadSummary()
            actions.loadDescriptions()
            actions.loadIntentCoverage()
            actions.loadDailyStats()
            actions.loadFailureRows()
            actions.loadSampleIntentRows()
            actions.loadNeighborsBeforeRows()
            actions.loadNeighborsAfterRows()
            actions.loadByHarnessRows()
            actions.loadTopUserRows()
        },
    })),

    // The window rides along in the URL from the Tool quality tab. Reading it here (rather than once
    // in afterMount) keeps the page in sync when only date_from / date_to change for the same tool —
    // e.g. browser back/forward — since the logic is keyed by toolName and wouldn't remount.
    urlToAction(({ actions, values, cache }) => ({
        [`${urls.mcpAnalyticsToolQuality()}/:toolName`]: (_, searchParams) => {
            const dateFrom =
                typeof searchParams.date_from === 'string' ? searchParams.date_from : DEFAULT_DATE_FILTER.dateFrom
            const dateTo = typeof searchParams.date_to === 'string' ? searchParams.date_to : null
            const dateChanged = dateFrom !== values.dateFilter.dateFrom || dateTo !== values.dateFilter.dateTo
            if (dateChanged) {
                actions.setDateFilter(dateFrom, dateTo)
            }
            if (dateChanged || !cache.hasLoaded) {
                actions.loadAllSections()
            }
            cache.hasLoaded = true
        },
    })),
])
