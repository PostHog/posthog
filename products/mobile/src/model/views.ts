// The view models of the Views tab. Server times are ISO strings; `readAt` is device epoch ms.

import type { MetricChartKind, MetricFormat, MetricInterval, MetricPoint, MetricSeries } from './types'

/** `web_link` covers every other shortcut type (hog functions, product pages): it opens on the web. */
export type ViewKind = 'dashboard' | 'insight' | 'web_analytics' | 'notebook' | 'canvas' | 'web_link'

export type PinDisplayMode = 'row' | 'number' | 'chart'

/** Where a view was opened from, for `mobile_view_opened`. `dashboard`: a tile on a dashboard screen. */
export type ViewEntry = 'pinned' | 'recent' | 'browse' | 'search' | 'deep_link' | 'dashboard'

export interface ViewRef {
    kind: ViewKind
    /** Dashboard id as a string, insight or notebook `short_id`; null for web analytics and product pages. */
    ref: string | null
    /** The web path without the project prefix, such as `/dashboard/12`. */
    href: string | null
    name: string
}

/** How this phone shows a pin. Device-local; the Views list can choose a default when no preference exists. */
export interface PinDisplay {
    mode: PinDisplayMode
    /** A dashboard pin in Number or Chart mode reads this tile's insight with `from_dashboard`. */
    tileId?: number
    insightId?: number
    insightShortId?: string
}

export interface PinView extends ViewRef {
    /** The row the list keeps for this view. Local rank and display are keyed by it. */
    shortcutId: string
    /** Every row that matches this view, across environments. Unpin deletes all of them. */
    shortcutIds: string[]
    /** The shortcut's raw `type`, for the icon of a pin that opens on the web. */
    type: string
    /** Position in the server's order (`order`, then path). */
    serverOrder: number
    /** Device-local order; null sorts after ranked pins, in server order. */
    rank: number | null
    display: PinDisplay
    /** False: the app has no screen for it, so it opens on the web. */
    native: boolean
}

export interface RecentView extends ViewRef {
    viewedAt: string
    source: 'device' | 'server'
}

/** A row in Browse or in search results. */
export interface BrowseRow extends ViewRef {
    description: string | null
    /** Dashboards: this user's last web view. Insights: last modified. */
    at: string | null
}

/** A view opened on this phone, kept on the device for Recent. */
export interface DeviceRecentEntry {
    kind: 'dashboard' | 'insight' | 'web_analytics'
    ref: string | null
    name: string
    viewedAt: string
}

/** The refresh fields of one data item. They change only on a response with a result and no error. */
export interface Freshness {
    lastRefreshAt: string | null
    cacheTargetAge: string | null
    nextAllowedRefreshAt: string | null
    /** Device ms of the last response for this item, good or not. */
    readAt: number
    /** The last read failed. The other fields keep the last good values. */
    refreshFailed: boolean
}

export interface NumberDelta {
    previous: number
    /** `value - previous`, scaled to points for `percentage_scaled`. */
    change: number
    /** Percent change, null when `previous` is 0. */
    percent: number | null
    /** `points` for values that are already percentages: show `change`, not `percent`. */
    unit: 'percent' | 'points'
    /** `compare`: the previous period. `previous_bucket`: the bucket before the value's bucket. */
    basis: 'compare' | 'previous_bucket'
    /** The bucket the value is compared with, for "vs Oct 6". Null for window totals. */
    previousAt: string | null
}

export interface InsightSeriesView {
    key: string
    label: string
    points: MetricPoint[]
    /** `previous` marks the compare series of the period before. */
    compare: 'current' | 'previous' | null
    /** The series index in the trends query, for the actors query. */
    seriesIndex: number
    breakdownValue: string | number | null | (string | number | null)[]
}

export interface ResolvedRange {
    from: string
    to: string
}

/** The range the view saved: `query.source.dateRange`, or the dashboard's `filters`. */
export interface SavedRange {
    dateFrom: string | null
    dateTo: string | null
}

/** One funnel step and the people who reached it. */
export interface FunnelStepView {
    key: string
    /** The step's custom name, else its event or action name. */
    name: string
    count: number
    /** Percent of the people who entered the funnel at step 1. Null when nobody entered. */
    percentOfFirst: number | null
    /** Percent of the people who reached the step before. Null for step 1. */
    percentOfPrevious: number | null
    /** People who reached the step before but not this one. Null for step 1. */
    droppedOff: number | null
    /** Median seconds from the step before. Null for step 1, or when nobody converted. */
    medianSeconds: number | null
}

export interface FunnelView {
    steps: FunnelStepView[]
    /** Percent of step 1 that reached the last step. */
    conversion: number | null
    /** The breakdown values the steps add up. 0 without a breakdown. */
    breakdownValues: number
}

export type RetentionPeriodUnit = 'hour' | 'day' | 'week' | 'month'

export interface RetentionCellView {
    count: number
    /** 0 to 100, of the cohort size, or of the period before for `reference: 'previous'`. */
    percent: number
}

export interface RetentionCohortView {
    key: string
    /** Start of the cohort's period 0, ISO. */
    date: string
    /** People in the cohort: the count of period 0. */
    size: number
    /** From period 0, every period that has started. Periods still in the future are left out. */
    cells: RetentionCellView[]
}

export interface RetentionView {
    period: RetentionPeriodUnit
    /** "Week 0", "Week 1" and so on: one per period column. */
    periodLabels: string[]
    cohorts: RetentionCohortView[]
    reference: 'total' | 'previous'
}

/** One value of a ranking: a breakdown value, or a series when there is no breakdown. */
export interface RankedValueView {
    key: string
    label: string
    value: number
}

export interface SqlColumnView {
    name: string
    /** The ClickHouse type reduced to the web's scalar names: INTEGER, FLOAT, DECIMAL, STRING, DATE, DATETIME, BOOLEAN or other. */
    scalar: string
    isNumerical: boolean
    isDate: boolean
    /** From `tableSettings.columns[].settings.formatting`, else from the matching `chartSettings.yAxis` entry. */
    format: InsightPresentation | null
}

export type SqlCell = string | number | boolean | null

export interface SqlTableView {
    columns: SqlColumnView[]
    rows: SqlCell[][]
    /** The server cut the result at its limit, so `rows` is a prefix. */
    hasMore: boolean
}

export interface RankingView {
    /** Highest first. SQL rows keep the server's order, which the author chose. */
    rows: RankedValueView[]
    /** The sum of the rows, or null when the math counts distinct people, whom several rows can share. */
    total: number | null
}

export interface InsightCapabilities {
    number: boolean
    chart: boolean
    /** "View people" and "Watch recordings" at a point. */
    people: boolean
}

/** A saved insight's own number settings: a SQL column's `formatting`, or a trends insight's aggregation axis. */
export interface InsightPresentation {
    kind: 'sql' | 'trends'
    style: string | null
    prefix: string
    suffix: string
    decimalPlaces?: number
    minDecimalPlaces?: number
    /** Multiplies the value before it is formatted. The web's SQL table shows a percent column's fractions as percents. */
    scale?: number
}

export interface InsightValueFormat extends MetricFormat {
    presentation?: InsightPresentation
}

/** One read of an insight, as the list and the view screens see it. */
export interface InsightSnapshot extends Freshness {
    insightId: number
    shortId: string
    name: string
    description: string | null
    /** `TrendsQuery`, `FunnelsQuery`, `HogQLQuery` and so on. */
    queryKind: string | null
    /** The response's query, with the dashboard and tile layers applied. Compare and the Point sheet use its `source`. */
    query: unknown
    resolvedRange: ResolvedRange | null
    timezone: string | null
    savedRange: SavedRange
    interval: MetricInterval
    format: InsightValueFormat
    /** The big number. See `valueAt`. */
    value: number | null
    /** The bucket `value` is for. Null when `value` is the window's total. */
    valueAt: string | null
    previous: number | null
    delta: NumberDelta | null
    /** The first current series, for the number pin's sparkline. */
    series: MetricSeries | null
    allSeries: InsightSeriesView[]
    /** Line or bar for a trends display over time, with any number of series and breakdowns. */
    chartKind: MetricChartKind | null
    /** Funnel steps of a `FunnelsQuery` in the steps layout. */
    funnel: FunnelView | null
    retention: RetentionView | null
    /** Totals per breakdown value or series, for value bars, tables and pies. */
    ranking: RankingView | null
    /** The result of a SQL insight (`HogQLQuery`), whatever its display. Null for other kinds. */
    sqlTable: SqlTableView | null
    /** Start of the bucket that contains now. It is never complete. */
    inProgressFrom: string | null
    /** On a dashboard: the tile ignores the dashboard range. */
    usesOwnRange: boolean
    capabilities: InsightCapabilities
    /** "Line", "Bar", "Big number", "Funnel" and so on. */
    kindLabel: string
    /** The last good response computed fresh instead of reading the cache. */
    computed: boolean
    /** The author's name, for the About sheet. */
    createdBy: string | null
    createdAt: string | null
}

export interface DashboardTileView {
    tileId: number
    kind: 'insight' | 'text'
    insightId: number | null
    shortId: string | null
    name: string
    text: string | null
    /** Shows "Uses its own range". */
    usesOwnRange: boolean
    /** A SQL tile without `{filters}`: the app reads it without the range override. */
    ignoresRangeOverride: boolean
    capabilities: InsightCapabilities
    kindLabel: string
    /** Why a pin cannot show the tile: a trends insight with several series, or with a breakdown. */
    seriesCount: number
    hasBreakdown: boolean
}

export interface DashboardView {
    id: number
    name: string
    description: string | null
    savedRange: SavedRange
    /** `Dashboard.last_refresh`, shared by every viewer. Only the bulk refresh rule reads it. */
    lastRefresh: string | null
    /** In phone order: the web's one-column layout. */
    tiles: DashboardTileView[]
}

export interface WebOverviewMetric {
    key: string
    label: string
    format: MetricFormat
    value: number | null
    previous: number | null
    changePercent: number | null
    isIncreaseBad: boolean
}

export interface WebOverviewSnapshot extends Freshness {
    metrics: WebOverviewMetric[]
    resolvedRange: ResolvedRange | null
    timezone: string | null
    computed: boolean
}

/** A person at a chart point. */
export interface ActorRow {
    id: string
    name: string
    /** Session ids that matched, for "Watch recordings". Empty without `includeRecordings`. */
    recordings: string[]
}

export type RangePresetKey =
    | 'today'
    | 'yesterday'
    | '24h'
    | '7d'
    | '30d'
    | '90d'
    | 'this_week'
    | 'this_month'
    | 'last_month'
    | 'this_year'
    | 'all'
    | '1h'
    | '48h'
    | '14d'
    | '180d'
    | 'last_week'

/** How a stepped range moves: one calendar unit, a rolling window of whole days, or a window of hours. */
export type RangeStepUnit = 'day' | 'week' | 'month' | 'year' | 'days' | 'hours'

/** A range the user picked for this session. `null` elsewhere means the view's saved range. */
export type RangeChoice =
    | { kind: 'preset'; key: RangePresetKey }
    | {
          kind: 'fixed'
          /** `YYYY-MM-DD` in the project timezone, or an ISO datetime when `explicitDate`. */
          dateFrom: string
          dateTo: string
          explicitDate: boolean
          unit: RangeStepUnit
          /** The preset a step started from, so stepping back to its window returns to it. */
          origin: RangePresetKey | null
      }
