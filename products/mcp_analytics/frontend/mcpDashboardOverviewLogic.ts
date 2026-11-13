import {
    MakeLogicType,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    listeners,
    path,
    reducers,
    selectors,
} from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { shouldReportApiFailure } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { type FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'lib/posthog-typed'
import { getDefaultInterval } from 'lib/utils/dateFilters'
import { uuid } from 'lib/utils/dom'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import {
    type ComparisonWindow,
    buildBucketKeys,
    buildComparisonWindow,
    lastBucketIsInProgress,
    normalizeBucket,
} from 'lib/utils/timeBuckets'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { pageCollectionId } from '~/queries/nodes/DataNode/pageCollections'
import {
    CachedMCPDashboardQueryResponse,
    HogQLFilters,
    MCPAnalyticsPropertyFilter,
    MCPDashboardQuery,
    MCPDashboardSection,
    MCPDashboardSectionResult,
    MCPHarnessBreakdownItem,
    MCPModelBreakdownItem,
    MCPToolCallsAndErrorsItem,
    NodeKind,
} from '~/queries/schema/schema-general'
import { AnyPropertyFilter, IntervalType } from '~/types'

import { mcpClusteringLogic } from './clustering/mcpClusteringLogic'
import type { MCPIntentClusterApi } from './generated/api.schemas'
import { type MCPSharedQueryFilters, mcpAnalyticsFiltersLogic } from './mcpAnalyticsFiltersLogic'
import { mcpToolReportUrl } from './mcpAnalyticsToolQualityLogic'

export interface DateFilter {
    dateFrom: string | null
    dateTo: string | null
}

const DEFAULT_DATE_FILTER: DateFilter = { dateFrom: '-7d', dateTo: null }

function dateFilterFromUrl(searchParams: Record<string, any>): DateFilter {
    return {
        dateFrom: typeof searchParams.date_from === 'string' ? searchParams.date_from : DEFAULT_DATE_FILTER.dateFrom,
        dateTo: typeof searchParams.date_to === 'string' ? searchParams.date_to : null,
    }
}

function dashboardUrlMovesDate(dateFilter: DateFilter): boolean {
    const { pathname, searchParams } = router.values.currentLocation
    if (removeProjectIdIfPresent(pathname) !== urls.mcpAnalyticsDashboard()) {
        return false
    }
    const { dateFrom, dateTo } = dateFilterFromUrl(searchParams)
    return dateFrom !== dateFilter.dateFrom || dateTo !== dateFilter.dateTo
}

const MCP_DASHBOARD_DATA_COLLECTION_ID = pageCollectionId('mcp-analytics-dashboard')
const DASHBOARD_TILE_ID = 'mcp-dashboard'

// The leaderboard draws protocol versions and tools from its own facets. It keeps modelRows as the model
// chart's fallback when the model facet fails.
const DASHBOARD_SECTIONS: readonly MCPDashboardSection[] = [
    MCPDashboardSection.Kpis,
    MCPDashboardSection.PeriodTotals,
    MCPDashboardSection.ToolRows,
    MCPDashboardSection.SessionRows,
    MCPDashboardSection.HarnessRows,
    MCPDashboardSection.ModelRows,
    MCPDashboardSection.ActivityRows,
    MCPDashboardSection.Model,
    MCPDashboardSection.ProtocolVersion,
    MCPDashboardSection.Tool,
    MCPDashboardSection.ErrorType,
    MCPDashboardSection.LabUsers,
    MCPDashboardSection.NamedModelUsers,
    MCPDashboardSection.Reliability,
]

// These cards hide when they have no rows, so a failure would read as no data without a toast.
const SECTIONS_WITHOUT_ERROR_STATE = [MCPDashboardSection.ModelRows]

export interface LoadedSection extends MCPDashboardSectionResult {
    /** The KPI split point of the window the section was computed on. */
    currentStartBucket: string
}

export type SectionResults = Partial<Record<MCPDashboardSection, LoadedSection>>

export type SectionFlags = Partial<Record<MCPDashboardSection, boolean>>

export function sectionRows<T>(sections: SectionResults, section: MCPDashboardSection): T[] {
    return (sections[section]?.results as T[] | undefined) ?? []
}

interface SectionsResponse {
    results: SectionResults
    isCached: boolean
    requestError?: unknown
}

async function requestSections(query: MCPDashboardQuery): Promise<SectionsResponse> {
    const { currentStartBucket } = query.comparison
    try {
        const response = (await api.query(query)) as CachedMCPDashboardQueryResponse
        const results = Object.entries(response.results).map(([section, result]) => [
            section,
            { ...result, currentStartBucket },
        ])
        return { results: Object.fromEntries(results), isCached: response.is_cached }
    } catch (requestError) {
        const results = query.sections.map((section) => [section, { error: String(requestError), currentStartBucket }])
        return { results: Object.fromEntries(results), isCached: false, requestError }
    }
}

// Matches initKea's loader failure toast, which skips a request without a status and the 401 and 403 the app
// handles elsewhere.
function isToastedStatus(error: unknown): boolean {
    const status = (error as { status?: unknown } | null)?.status
    return typeof status === 'number' && ![401, 403, 409].includes(status)
}

// Cards with an error state only report to error tracking. A one-section request's failure is that section's
// own, so it toasts for the cards that hide; a failed batch says nothing about any one section, so it doesn't.
// The server captures each section that fails inside a batch, so only request failures are captured here.
function reportFailures({ results, requestError }: SectionsResponse, owned: MCPDashboardSection[]): void {
    if (requestError !== undefined && shouldReportApiFailure(requestError)) {
        posthog.captureException(requestError, { action: 'load-mcp-dashboard-sections', sections: owned })
    }
    const failedOnItsOwn =
        requestError === undefined
            ? (section: MCPDashboardSection): boolean => !!results[section]?.error
            : () => Object.keys(results).length === 1 && isToastedStatus(requestError)
    if (owned.some((section) => SECTIONS_WITHOUT_ERROR_STATE.includes(section) && failedOnItsOwn(section))) {
        lemonToast.error(
            "Couldn't load the model or protocol version breakdown. Try again, or pick a shorter date range.",
            { toastId: 'mcp-dashboard-breakdown-failed' }
        )
    }
}

export interface BucketRow {
    bucket: string
    sessions: number
    tool_calls: number
    errors: number
    p95: number
}

export interface KPIMetric {
    value: number
    previousValue: number
    deltaPct: number | null
    sparkline: number[]
    sparklineLabels: string[]
    goodDirection: 'up' | 'down'
}

export interface KPIData {
    sessions: KPIMetric
    toolCalls: KPIMetric
    errorRatePct: KPIMetric
    p95LatencyMs: KPIMetric
}

// Window-level figures that can't be summed from per-bucket rows: distinct users and a percentile.
export interface PeriodTotals {
    users: KPIMetric
    p95LatencyMs: KPIMetric
}

export interface ToolRow {
    tool: string
    total_calls: number
    errors: number
    error_rate_pct: number
    p95_duration_ms: number
}

export interface ActivityRow {
    day: string
    successes: number
    errors: number
}

export interface DailyActivity {
    labels: string[]
    successes: number[]
    errors: number[]
}

export interface HarnessRow {
    category: string
    total_calls: number
    errors: number
    error_rate_pct: number
    sessions: number
}

export function toHarnessRow(item: MCPHarnessBreakdownItem): HarnessRow {
    return {
        category: item.harness,
        total_calls: item.total_calls,
        errors: item.errors,
        error_rate_pct: item.error_rate_pct,
        sessions: item.sessions,
    }
}

export interface ModelRow {
    model: string
    total_calls: number
}

export interface SessionRow {
    session_id: string
    tool_calls: number
    errors: number
    error_rate_pct: number
    duration_seconds: number
    distinct_tools: number
    last_seen: string
}

export type NotableRule = 'worst_error_rate' | 'all_fail' | 'most_exploratory' | 'exemplar' | 'high_activity'

// Calls the busiest session needs before it is worth flagging. Absolute rather than relative to the
// median, because the query returns the 500 busiest sessions, so the median of what we get is not the
// account's median.
const MIN_OUTLIER_CALLS = 5

// Below this, a session is an ordinary task rather than an exploration.
const MIN_JOURNEY_TOOLS = 4

export interface NotableSession {
    rule: NotableRule
    label: string
    session: SessionRow
}

const EMPTY_METRIC: KPIMetric = {
    value: 0,
    previousValue: 0,
    deltaPct: null,
    sparkline: [],
    sparklineLabels: [],
    goodDirection: 'up',
}
const EMPTY_PERIOD_TOTALS: PeriodTotals = {
    users: { ...EMPTY_METRIC, goodDirection: 'up' },
    p95LatencyMs: { ...EMPTY_METRIC, goodDirection: 'down' },
}
const EMPTY_KPIS: KPIData = {
    sessions: { ...EMPTY_METRIC, goodDirection: 'up' },
    toolCalls: { ...EMPTY_METRIC, goodDirection: 'up' },
    errorRatePct: { ...EMPTY_METRIC, goodDirection: 'down' },
    p95LatencyMs: { ...EMPTY_METRIC, goodDirection: 'down' },
}

export function deltaPct(current: number, previous: number): number | null {
    if (previous === 0) {
        return current === 0 ? 0 : null
    }
    return ((current - previous) / previous) * 100
}

// Window resolution, bucket keys, the comparison window, and the bucket-key format are shared with the
// tab and detail surfaces. See lib/utils/timeBuckets.

// Project the daily success/error rows onto the full set of buckets, defaulting empty buckets to 0.
export function buildDailyActivity(rows: ActivityRow[], bucketKeys: string[]): DailyActivity {
    const byDay = new Map(rows.map((r) => [r.day, r]))
    return {
        labels: bucketKeys,
        successes: bucketKeys.map((k) => byDay.get(k)?.successes ?? 0),
        errors: bucketKeys.map((k) => byDay.get(k)?.errors ?? 0),
    }
}

// The window opens on a whole minute so the KPI and Users queries keep one cache key for that minute
// instead of a new one per millisecond. A minute is the most the previous period may grow: rounding to
// a whole bucket would make it up to a bucket longer than the selected period and skew every delta.
function kpiComparisonWindow(dateFilter: DateFilter, timezone: string, interval: IntervalType): ComparisonWindow {
    const window = buildComparisonWindow(dateFilter.dateFrom, dateFilter.dateTo, timezone, interval)
    return { ...window, dateFrom: dayjs(window.dateFrom).startOf('minute').toISOString() }
}

function parseRows(rawRows: unknown[][]): BucketRow[] {
    return rawRows.map((r) => ({
        bucket: String(r[0]),
        sessions: Number(r[1] ?? 0),
        tool_calls: Number(r[2] ?? 0),
        errors: Number(r[3] ?? 0),
        p95: Number(r[4] ?? 0),
    }))
}

// With a handful of calls, one failure or one slow call decides the rank, so ranking needs a minimum sample.
export const MIN_CALLS_TO_RANK_TOOLS = 20

export function rankToolsByErrorRate(rows: ToolRow[]): ToolRow[] {
    return rows
        .filter((r) => r.total_calls >= MIN_CALLS_TO_RANK_TOOLS)
        .sort((a, b) => b.error_rate_pct - a.error_rate_pct)
}

// A p95 of 0 means no call in the range carried a duration, not an instant tool.
export function rankToolsByP95(rows: ToolRow[]): ToolRow[] {
    return rows
        .filter((r) => r.total_calls >= MIN_CALLS_TO_RANK_TOOLS && r.p95_duration_ms > 0)
        .sort((a, b) => b.p95_duration_ms - a.p95_duration_ms)
}

export function rankedToolsEmptyMessage(rows: ToolRow[]): string | undefined {
    return rows.length > 0 ? `No tool has ${MIN_CALLS_TO_RANK_TOOLS} or more calls in this date range yet.` : undefined
}

export function slowestToolsEmptyMessage(rows: ToolRow[]): string | undefined {
    return rows.some((r) => r.total_calls >= MIN_CALLS_TO_RANK_TOOLS)
        ? 'No tool calls in this date range have a recorded duration.'
        : rankedToolsEmptyMessage(rows)
}

// Buckets at or after `currentStartBucket` belong to the selected window; the
// rest are the equal-length window immediately before it.
export function buildKPIs(rows: BucketRow[], currentStartBucket: string): KPIData {
    const current = rows.filter((r) => r.bucket >= currentStartBucket).sort((a, b) => a.bucket.localeCompare(b.bucket))
    const previous = rows.filter((r) => r.bucket < currentStartBucket)

    const errorRate = (rows_: BucketRow[]): number => {
        const calls = rows_.reduce((acc, r) => acc + r.tool_calls, 0)
        return calls ? (rows_.reduce((acc, r) => acc + r.errors, 0) / calls) * 100 : 0
    }

    const curSessions = current.reduce((acc, r) => acc + r.sessions, 0)
    const curCalls = current.reduce((acc, r) => acc + r.tool_calls, 0)

    const prevSessions = previous.reduce((acc, r) => acc + r.sessions, 0)
    const prevCalls = previous.reduce((acc, r) => acc + r.tool_calls, 0)

    const curErrorRate = errorRate(current)
    const prevErrorRate = errorRate(previous)
    const sparklineLabels = current.map((r) => r.bucket)

    return {
        sessions: {
            value: curSessions,
            previousValue: prevSessions,
            deltaPct: deltaPct(curSessions, prevSessions),
            sparkline: current.map((r) => r.sessions),
            sparklineLabels,
            goodDirection: 'up',
        },
        toolCalls: {
            value: curCalls,
            previousValue: prevCalls,
            deltaPct: deltaPct(curCalls, prevCalls),
            sparkline: current.map((r) => r.tool_calls),
            sparklineLabels,
            goodDirection: 'up',
        },
        errorRatePct: {
            value: curErrorRate,
            previousValue: prevErrorRate,
            deltaPct: deltaPct(curErrorRate, prevErrorRate),
            sparkline: current.map((r) => (r.tool_calls ? (r.errors / r.tool_calls) * 100 : 0)),
            sparklineLabels,
            goodDirection: 'down',
        },
        // The headline value comes from PeriodTotals; a period p95 can't be built from bucket p95s.
        p95LatencyMs: {
            ...EMPTY_METRIC,
            sparkline: current.map((r) => r.p95),
            sparklineLabels,
            goodDirection: 'down',
        },
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpDashboardOverviewLogicValues {
    sharedQueryFilters: MCPSharedQueryFilters // mcpAnalyticsFiltersLogic
    clusters: readonly MCPIntentClusterApi[] // mcpClusteringLogic
    hasSnapshot: boolean // mcpClusteringLogic
    totalClusterCount: number // mcpClusteringLogic
    currentTeamId: number | null // teamLogic
    timezone: string // teamLogic
    activityIncompleteTail: boolean
    activityRows: ActivityRow[]
    bucketKeys: string[]
    canShowFeedback: boolean
    dailyActivity: DailyActivity
    dashboardBatched: boolean
    dashboardLoading: boolean
    dateFilter: DateFilter
    failedLoads: SectionFlags
    feedbackContextKey: string
    feedbackLoadFailed: boolean
    harnessRows: HarnessRow[]
    hasFilterInteraction: boolean
    hasModelData: boolean
    headlineKpis: KPIData
    intentClusterCount: KPIMetric
    interval: IntervalType
    kpiIncompleteTail: boolean
    kpis: KPIData
    loadingSections: SectionFlags
    modelRows: ModelRow[]
    notableSessions: NotableSession[]
    periodTotals: PeriodTotals
    queryFilters: HogQLFilters
    sections: SectionResults
    sessionRows: SessionRow[]
    toolRows: ToolRow[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpDashboardOverviewLogicActions {
    collectionNodeLoadData: (
        id: string,
        kind?: string | undefined
    ) => {
        id: string
        kind: string | undefined
    } // dataNodeCollectionLogic
    collectionNodeLoadDataFailure: (id: string) => {
        id: string
    } // dataNodeCollectionLogic
    collectionNodeLoadDataSuccess: (
        id: string,
        meta?: import('~/queries/nodes/DataNode/dataNodeCollectionLogic').CollectionNodeLoadMeta | undefined
    ) => {
        id: string
        meta: import('~/queries/nodes/DataNode/dataNodeCollectionLogic').CollectionNodeLoadMeta | undefined
    } // dataNodeCollectionLogic
    endPageVisit: () => {
        value: true
    } // dataNodeCollectionLogic
    startPageVisit: (visitId: string) => {
        visitId: string
    } // dataNodeCollectionLogic
    setFeatureFlags: (
        flags: string[],
        variants: Record<string, boolean | string>
    ) => {
        flags: string[]
        variants: Record<string, boolean | string>
    } // featureFlagLogic
    setFilterTestAccounts: (filterTestAccounts: boolean | null) => {
        filterTestAccounts: boolean | null
    } // mcpAnalyticsFiltersLogic
    setPropertyFilters: (properties: AnyPropertyFilter[]) => {
        properties: AnyPropertyFilter[]
    } // mcpAnalyticsFiltersLogic
    loadDashboard: () => {
        value: true
    }
    loadSections: (
        sections: MCPDashboardSection[],
        fullLoad?: boolean
    ) => {
        fullLoad: boolean
        sections: MCPDashboardSection[]
    }
    markFilterInteraction: () => {
        value: true
    }
    openToolReport: (tool: string) => {
        tool: string
    }
    reloadAll: () => {
        value: true
    }
    sectionsLoaded: (results: SectionResults) => {
        results: Partial<Record<MCPDashboardSection, LoadedSection>>
    }
    setDateFilter: (
        dateFrom: string | null,
        dateTo: string | null
    ) => {
        dateFrom: string | null
        dateTo: string | null
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpDashboardOverviewLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        dashboardBatched: (featureFlags: FeatureFlagsSet) => boolean
        dashboardLoading: (loadingSections: Partial<Record<MCPDashboardSection, boolean>>) => boolean
        failedLoads: (sections: Partial<Record<MCPDashboardSection, LoadedSection>>) => SectionFlags
        feedbackLoadFailed: (failedLoads: Partial<Record<MCPDashboardSection, boolean>>) => boolean
        kpis: (sections: Partial<Record<MCPDashboardSection, LoadedSection>>) => KPIData
        periodTotals: (sections: Partial<Record<MCPDashboardSection, LoadedSection>>) => PeriodTotals
        toolRows: (sections: Partial<Record<MCPDashboardSection, LoadedSection>>) => ToolRow[]
        sessionRows: (sections: Partial<Record<MCPDashboardSection, LoadedSection>>) => SessionRow[]
        harnessRows: (sections: Partial<Record<MCPDashboardSection, LoadedSection>>) => HarnessRow[]
        modelRows: (sections: Partial<Record<MCPDashboardSection, LoadedSection>>) => ModelRow[]
        activityRows: (sections: Partial<Record<MCPDashboardSection, LoadedSection>>) => ActivityRow[]
        canShowFeedback: (
            hasFilterInteraction: boolean,
            dashboardLoading: boolean,
            feedbackLoadFailed: boolean,
            kpis: KPIData
        ) => boolean
        feedbackContextKey: (currentTeamId: number | null) => string
        queryFilters: (
            dateFilter: DateFilter,
            sharedQueryFilters: Required<Pick<HogQLFilters, 'filterTestAccounts' | 'properties'>>
        ) => HogQLFilters
        interval: (dateFilter: DateFilter) => IntervalType
        bucketKeys: (dateFilter: DateFilter, timezone: string, interval: IntervalType) => string[]
        activityIncompleteTail: (bucketKeys: string[], timezone: string, interval: IntervalType) => boolean
        headlineKpis: (kpis: KPIData, periodTotals: PeriodTotals) => KPIData
        kpiIncompleteTail: (kpis: KPIData, timezone: string, interval: IntervalType) => boolean
        dailyActivity: (activityRows: ActivityRow[], bucketKeys: string[]) => DailyActivity
        notableSessions: (sessionRows: SessionRow[]) => NotableSession[]
        hasModelData: (modelRows: ModelRow[]) => boolean
        intentClusterCount: (totalClusterCount: number) => KPIMetric
    }
}

export type mcpDashboardOverviewLogicType = MakeLogicType<
    mcpDashboardOverviewLogicValues,
    mcpDashboardOverviewLogicActions,
    Record<string, any>,
    mcpDashboardOverviewLogicMeta
>

export const mcpDashboardOverviewLogic = kea<mcpDashboardOverviewLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'mcpDashboardOverviewLogic']),
    connect(() => ({
        values: [
            mcpClusteringLogic,
            ['clusters', 'hasSnapshot', 'totalClusterCount'],
            teamLogic,
            ['timezone', 'currentTeamId'],
            mcpAnalyticsFiltersLogic,
            ['queryFilters as sharedQueryFilters'],
        ],
        actions: [
            mcpAnalyticsFiltersLogic,
            ['setFilterTestAccounts', 'setPropertyFilters'],
            featureFlagLogic,
            ['setFeatureFlags'],
            dataNodeCollectionLogic({ key: MCP_DASHBOARD_DATA_COLLECTION_ID }),
            [
                'collectionNodeLoadData',
                'collectionNodeLoadDataSuccess',
                'collectionNodeLoadDataFailure',
                'startPageVisit',
                'endPageVisit',
            ],
        ],
    })),
    actions({
        setDateFilter: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        reloadAll: true,
        markFilterInteraction: true,
        openToolReport: (tool: string) => ({ tool }),
        loadDashboard: true,
        loadSections: (sections: MCPDashboardSection[], fullLoad: boolean = false) => ({ sections, fullLoad }),
        sectionsLoaded: (results: SectionResults) => ({ results }),
    }),
    reducers({
        hasFilterInteraction: [false, { markFilterInteraction: () => true }],
        // A section keeps its rows while it reloads, like the per-card loaders did, but drops its error so a
        // retried card shows its loading state.
        sections: [
            {} as SectionResults,
            {
                loadSections: (state, { sections }) =>
                    Object.fromEntries(
                        Object.entries(state).filter(
                            ([section, result]) => !(sections.includes(section as MCPDashboardSection) && result.error)
                        )
                    ),
                sectionsLoaded: (state, { results }) => ({ ...state, ...results }),
            },
        ],
        loadingSections: [
            {} as SectionFlags,
            {
                // A full load replaces the layout, so a section it no longer shows stops counting as loading.
                loadSections: (state, { sections, fullLoad }) => ({
                    ...(fullLoad ? {} : state),
                    ...Object.fromEntries(sections.map((section) => [section, true])),
                }),
                sectionsLoaded: (state, { results }) =>
                    Object.fromEntries(Object.entries(state).filter(([section]) => !(section in results))),
            },
        ],
        dateFilter: [
            DEFAULT_DATE_FILTER,
            {
                setDateFilter: (_, { dateFrom, dateTo }): DateFilter => ({ dateFrom, dateTo }),
            },
        ],
    }),
    selectors({
        dashboardBatched: [
            () => [featureFlagLogic.selectors.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean => !!featureFlags[FEATURE_FLAGS.MCP_ANALYTICS_DASHBOARD_BATCH],
        ],
        dashboardLoading: [
            (s) => [s.loadingSections],
            (loadingSections: SectionFlags): boolean => Object.values(loadingSections).some(Boolean),
        ],
        failedLoads: [
            (s) => [s.sections],
            (sections: SectionResults): SectionFlags =>
                Object.fromEntries(
                    DASHBOARD_SECTIONS.filter((section) => !!sections[section]?.error).map((section) => [section, true])
                ),
        ],
        feedbackLoadFailed: [
            (s) => [s.failedLoads],
            (failedLoads: SectionFlags): boolean => Object.values(failedLoads).some(Boolean),
        ],
        kpis: [
            (s) => [s.sections],
            (sections: SectionResults): KPIData =>
                sections[MCPDashboardSection.Kpis]?.results
                    ? buildKPIs(
                          parseRows(sectionRows<unknown[]>(sections, MCPDashboardSection.Kpis)),
                          sections[MCPDashboardSection.Kpis].currentStartBucket
                      )
                    : EMPTY_KPIS,
        ],
        periodTotals: [
            (s) => [s.sections],
            (sections: SectionResults): PeriodTotals => {
                if (!sections[MCPDashboardSection.PeriodTotals]?.results) {
                    return EMPTY_PERIOD_TOTALS
                }
                // No calls in either period still compares zero with zero, so the tiles show a 0% change.
                const row = sectionRows<unknown[]>(sections, MCPDashboardSection.PeriodTotals)[0] ?? []
                const metric = (
                    value: number,
                    previousValue: number,
                    goodDirection: KPIMetric['goodDirection']
                ): KPIMetric => ({
                    value,
                    previousValue,
                    deltaPct: deltaPct(value, previousValue),
                    sparkline: [],
                    sparklineLabels: [],
                    goodDirection,
                })
                return {
                    users: metric(Number(row[0] ?? 0), Number(row[1] ?? 0), 'up'),
                    p95LatencyMs: metric(Number(row[2] ?? 0), Number(row[3] ?? 0), 'down'),
                }
            },
        ],
        toolRows: [
            (s) => [s.sections],
            (sections: SectionResults): ToolRow[] =>
                sectionRows<unknown[]>(sections, MCPDashboardSection.ToolRows).map((r) => ({
                    tool: String(r[0] ?? ''),
                    total_calls: Number(r[1] ?? 0),
                    errors: Number(r[2] ?? 0),
                    error_rate_pct: Number(r[3] ?? 0),
                    p95_duration_ms: Number(r[4] ?? 0),
                })),
        ],
        sessionRows: [
            (s) => [s.sections],
            (sections: SectionResults): SessionRow[] =>
                sectionRows<unknown[]>(sections, MCPDashboardSection.SessionRows).map((r) => ({
                    session_id: String(r[0] ?? ''),
                    tool_calls: Number(r[1] ?? 0),
                    errors: Number(r[2] ?? 0),
                    error_rate_pct: Number(r[3] ?? 0),
                    duration_seconds: Number(r[4] ?? 0),
                    distinct_tools: Number(r[5] ?? 0),
                    last_seen: String(r[6] ?? ''),
                })),
        ],
        harnessRows: [
            (s) => [s.sections],
            (sections: SectionResults): HarnessRow[] =>
                sectionRows<MCPHarnessBreakdownItem>(sections, MCPDashboardSection.HarnessRows).map(toHarnessRow),
        ],
        modelRows: [
            (s) => [s.sections],
            (sections: SectionResults): ModelRow[] =>
                sectionRows<MCPModelBreakdownItem>(sections, MCPDashboardSection.ModelRows),
        ],
        activityRows: [
            (s) => [s.sections],
            (sections: SectionResults): ActivityRow[] =>
                sectionRows<MCPToolCallsAndErrorsItem>(sections, MCPDashboardSection.ActivityRows).map((r) => ({
                    day: normalizeBucket(r.bucket),
                    successes: r.successes,
                    errors: r.errors,
                })),
        ],
        canShowFeedback: [
            (s) => [s.hasFilterInteraction, s.dashboardLoading, s.feedbackLoadFailed, s.kpis],
            (interacted: boolean, loading: boolean, failed: boolean, kpis: KPIData): boolean =>
                interacted && !loading && !failed && kpis.toolCalls.value > 0,
        ],
        feedbackContextKey: [(s) => [s.currentTeamId], (teamId: number | null): string => String(teamId ?? undefined)],
        queryFilters: [
            (s) => [s.dateFilter, s.sharedQueryFilters],
            (dateFilter: DateFilter, sharedQueryFilters: MCPSharedQueryFilters): HogQLFilters => ({
                dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                ...sharedQueryFilters,
            }),
        ],
        interval: [
            (s) => [s.dateFilter],
            (dateFilter: DateFilter): IntervalType => getDefaultInterval(dateFilter.dateFrom, dateFilter.dateTo),
        ],
        bucketKeys: [
            (s) => [s.dateFilter, s.timezone, s.interval],
            (dateFilter: DateFilter, timezone: string, interval: IntervalType): string[] =>
                buildBucketKeys(dateFilter.dateFrom, dateFilter.dateTo, timezone, interval),
        ],
        // Whether the activity chart's final bucket is the current, still-running interval — the
        // chart dashes that segment so a partial period doesn't read as a drop in tool calls.
        activityIncompleteTail: [
            (s) => [s.bucketKeys, s.timezone, s.interval],
            (bucketKeys: string[], timezone: string, interval: IntervalType): boolean =>
                lastBucketIsInProgress(bucketKeys, timezone, interval),
        ],
        // Read off the KPI sparkline's own labels, not `bucketKeys`: the sparkline is not zero-filled,
        // so on a day with no calls yet its last point is yesterday, which is settled.
        headlineKpis: [
            (s) => [s.kpis, s.periodTotals],
            (kpis: KPIData, periodTotals: PeriodTotals): KPIData => ({
                ...kpis,
                p95LatencyMs: {
                    ...kpis.p95LatencyMs,
                    ...periodTotals.p95LatencyMs,
                    sparkline: kpis.p95LatencyMs.sparkline,
                    sparklineLabels: kpis.p95LatencyMs.sparklineLabels,
                },
            }),
        ],
        kpiIncompleteTail: [
            (s) => [s.kpis, s.timezone, s.interval],
            (kpis: KPIData, timezone: string, interval: IntervalType): boolean =>
                lastBucketIsInProgress(kpis.sessions.sparklineLabels, timezone, interval),
        ],
        dailyActivity: [
            (s) => [s.activityRows, s.bucketKeys],
            (rows: ActivityRow[], bucketKeys: string[]): DailyActivity => buildDailyActivity(rows, bucketKeys),
        ],
        notableSessions: [
            (s) => [s.sessionRows],
            (sessionRows: SessionRow[]): NotableSession[] => pickNotableSessions(sessionRows),
        ],
        hasModelData: [
            (s) => [s.modelRows],
            (modelRows: ModelRow[]): boolean => modelRows.some((row) => row.total_calls > 0),
        ],
        intentClusterCount: [
            // The snapshot only stores the top clusters by call volume — report
            // the run's true count, not the length of the truncated list.
            (s) => [s.totalClusterCount],
            (totalClusterCount: number): KPIMetric => ({
                value: totalClusterCount,
                previousValue: 0,
                deltaPct: null,
                sparkline: [],
                sparklineLabels: [],
                goodDirection: 'up',
            }),
        ],
    }),
    listeners(({ actions, values, cache }) => {
        return {
            setDateFilter: () => {
                actions.reloadAll()
            },
            openToolReport: ({ tool }) => {
                router.actions.push(mcpToolReportUrl(tool, values.dateFilter))
            },
            setFilterTestAccounts: () => {
                actions.markFilterInteraction()
            },
            setPropertyFilters: () => {
                actions.markFilterInteraction()
            },
            // Flags can resolve after the first load, and a load's time to see data must be reported under the
            // batch arm that ran it.
            setFeatureFlags: () => {
                const { requestedArm } = cache
                if (requestedArm && requestedArm.batched !== values.dashboardBatched) {
                    actions.loadDashboard()
                }
            },
            reloadAll: () => {
                actions.loadDashboard()
            },
            loadDashboard: () => {
                cache.requestedArm = { batched: values.dashboardBatched }
                actions.collectionNodeLoadData(DASHBOARD_TILE_ID, NodeKind.MCPDashboardQuery)
                actions.loadSections([...DASHBOARD_SECTIONS], true)
            },
            // Each section belongs to the load that last asked for it, so a reload or retry drops a slower,
            // older answer for that section, even a failure.
            loadSections: async ({ sections, fullLoad }) => {
                const loadId = (cache.lastLoadId = (cache.lastLoadId ?? 0) + 1)
                cache.sectionLoads = {
                    ...cache.sectionLoads,
                    ...Object.fromEntries(sections.map((section) => [section, loadId])),
                }
                if (fullLoad) {
                    cache.fullLoadId = loadId
                }
                const { dateFilter, interval, sharedQueryFilters } = values
                const window = kpiComparisonWindow(dateFilter, values.timezone, interval)
                const query: MCPDashboardQuery = {
                    kind: NodeKind.MCPDashboardQuery,
                    sections,
                    dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                    interval,
                    // The shared filter bar only offers event and person filters, which the server accepts.
                    properties: sharedQueryFilters.properties as MCPAnalyticsPropertyFilter[],
                    filterTestAccounts: sharedQueryFilters.filterTestAccounts,
                    comparison: { dateFrom: window.dateFrom, currentStartBucket: window.currentStartBucket },
                }
                // The flag's off arm sends one request per section, as the baseline the batch is measured against.
                const requests = values.dashboardBatched ? [sections] : sections.map((section) => [section])
                const responses = await Promise.all(
                    requests.map(async (requested) => {
                        const response = await requestSections({ ...query, sections: requested })
                        const owned = requested.filter((section) => cache.sectionLoads[section] === loadId)
                        if (owned.length > 0 && !cache.disposables.isDisposed) {
                            reportFailures(response, owned)
                            actions.sectionsLoaded(
                                Object.fromEntries(owned.map((section) => [section, response.results[section]]))
                            )
                        }
                        return response
                    })
                )
                if (cache.fullLoadId !== loadId || cache.disposables.isDisposed) {
                    return
                }
                if (responses.some((response) => Object.values(response.results).some((result) => result.error))) {
                    actions.collectionNodeLoadDataFailure(DASHBOARD_TILE_ID)
                } else {
                    actions.collectionNodeLoadDataSuccess(DASHBOARD_TILE_ID, {
                        isCached: responses.every((response) => response.isCached),
                    })
                }
            },
        }
    }),
    // The shared filters change from the filter bar, URL hydration, or the team's test-account default.
    // A dashboard URL that also moves the date reloads through setDateFilter instead, so the tiles load once.
    subscriptions(({ actions, values }) => ({
        sharedQueryFilters: (_: MCPSharedQueryFilters, previous: MCPSharedQueryFilters | undefined) => {
            if (previous && !dashboardUrlMovesDate(values.dateFilter)) {
                actions.reloadAll()
            }
        },
    })),
    // The collection reports a load the dashboard leaves unfinished only inside a page visit. This runs before
    // urlToAction's mount hook, which starts a deep link's load, because a visit that starts during a load ends it.
    afterMount(({ actions, cache }) => {
        actions.startPageVisit(uuid())
        const { searchParams } = router.values
        const hasUrlFilters = typeof searchParams.date_from === 'string' || typeof searchParams.date_to === 'string'
        if (!hasUrlFilters && !cache.hasLoaded) {
            cache.hasLoaded = true
            actions.reloadAll()
        }
    }),
    actionToUrl(({ values }) => {
        const syncUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => {
            const { currentLocation } = router.values
            const searchParams = { ...currentLocation.searchParams }
            if (values.dateFilter.dateFrom) {
                searchParams.date_from = values.dateFilter.dateFrom
            } else {
                delete searchParams.date_from
            }
            if (values.dateFilter.dateTo) {
                searchParams.date_to = values.dateFilter.dateTo
            } else {
                delete searchParams.date_to
            }
            return [currentLocation.pathname, searchParams, currentLocation.hashParams, { replace: true }]
        }
        return {
            setDateFilter: syncUrl,
        }
    }),
    // The shared property and test-account filters hydrate from the same URL in
    // mcpAnalyticsFiltersLogic, which mounts first (connected), so a deep-linked load below
    // already sees them.
    urlToAction(({ actions, values, cache }) => ({
        [urls.mcpAnalyticsDashboard()]: (_, searchParams) => {
            const { dateFrom, dateTo } = dateFilterFromUrl(searchParams)
            const dateChanged = dateFrom !== values.dateFilter.dateFrom || dateTo !== values.dateFilter.dateTo
            if (dateChanged) {
                actions.setDateFilter(dateFrom, dateTo)
            }
            // URL already matches state (e.g. default filters) and afterMount deferred — load once.
            if (!dateChanged && !cache.hasLoaded) {
                actions.reloadAll()
            }
            cache.hasLoaded = true
        },
    })),
    beforeUnmount(({ actions }) => {
        actions.endPageVisit()
    }),
])

function median(values: number[]): number {
    if (values.length === 0) {
        return 0
    }
    const sorted = [...values].sort((a, b) => a - b)
    const mid = Math.floor(sorted.length / 2)
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

// Pick at most one session per rule, so every row has a reason to be there. Deliberately returns
// short, or empty, when nothing qualifies.
export function pickNotableSessions(rows: SessionRow[]): NotableSession[] {
    if (rows.length === 0) {
        return []
    }

    const medianCalls = median(rows.map((r) => r.tool_calls))
    const medianDuration = median(rows.map((r) => r.duration_seconds))
    const busyThreshold = Math.max(medianCalls, 3)
    const used = new Set<string>()
    const picked: NotableSession[] = []

    const take = (rule: NotableRule, label: string, candidate: SessionRow | undefined): void => {
        if (!candidate || used.has(candidate.session_id)) {
            return
        }
        used.add(candidate.session_id)
        picked.push({ rule, label, session: candidate })
    }

    // 1. Worst error rate at high volume — top err% among above-median-volume sessions
    const highVolume = rows.filter((r) => r.tool_calls >= busyThreshold && r.error_rate_pct > 0)
    take(
        'worst_error_rate',
        'Worst error rate at high volume',
        [...highVolume].sort((a, b) => b.error_rate_pct - a.error_rate_pct || b.tool_calls - a.tool_calls)[0]
    )

    // 2. All-fail session — error_rate_pct === 100 AND tool_calls >= 3
    const allFail = rows.filter((r) => r.error_rate_pct >= 100 && r.tool_calls >= 3)
    take(
        'all_fail',
        'Every call failed, likely an auth scope issue',
        [...allFail].sort((a, b) => b.tool_calls - a.tool_calls)[0]
    )

    // 3. Most exploratory — highest distinct_tools count, among sessions that are journeys at all
    const journeys = rows.filter((r) => r.distinct_tools >= MIN_JOURNEY_TOOLS)
    take(
        'most_exploratory',
        'Most exploratory journey',
        [...journeys].sort((a, b) => b.distinct_tools - a.distinct_tools || b.tool_calls - a.tool_calls)[0]
    )

    // 4. Exemplar — zero errors, above-median calls, faster than median duration
    const exemplars = rows.filter(
        (r) => r.error_rate_pct === 0 && r.tool_calls >= busyThreshold && r.duration_seconds <= medianDuration
    )
    take('exemplar', 'Concise success', [...exemplars].sort((a, b) => b.tool_calls - a.tool_calls)[0])

    // 5. High activity — the busiest session, once it is busy enough to be worth reading. Being the
    // largest of a small set is not notable: on a quiet account that can be a single tool call.
    const busiest = [...rows].sort((a, b) => b.tool_calls - a.tool_calls)[0]
    if (busiest && busiest.tool_calls >= MIN_OUTLIER_CALLS) {
        take('high_activity', 'High activity', busiest)
    }

    return picked
}
