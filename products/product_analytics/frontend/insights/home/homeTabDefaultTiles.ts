import { RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { dateMapping, getDefaultInterval, startOfWeek } from 'lib/utils/dateFilters'
import { BUCKET_FORMAT, lastBucketIsInProgress, normalizeBucket } from 'lib/utils/timeBuckets'
import { urls } from 'scenes/urls'

import {
    DateRange,
    EventsNode,
    GroupNode,
    InsightVizNode,
    MathType,
    NodeKind,
    RetentionQuery,
    TrendsQuery,
    WebAnalyticsItemKind,
} from '~/queries/schema/schema-general'
import {
    BaseMathType,
    ChartDisplayType,
    DashboardTemplateStoredInsightTile,
    DashboardTemplateType,
    FilterLogicalOperator,
    IntervalType,
    PropertyMathType,
    PropertyFilterType,
    PropertyOperator,
    RetentionDashboardDisplayType,
    RetentionPeriod,
    TrendResult,
} from '~/types'

import { HOME_TAB_DEFAULT_DATE_RANGE, type HomeTabMetricKey } from './homeTabDefaultLogic'

/** A single-number stat shown in the compact tile row at the top of the Home tab. */
export interface HomeTabStatQuery {
    key: HomeTabMetricKey
    title: string
    kind: WebAnalyticsItemKind
    isIncreaseBad?: boolean
    query: TrendsQuery
    trendQuery?: TrendsQuery
    trendKey?: HomeTabMetricKey
    summary?: 'daily_average'
    description?: string
}

/** A full chart shown below the tile row, chosen via the chart picker. */
export interface HomeTabChartOption {
    key: string
    title: string
    description: string
    query: InsightVizNode<TrendsQuery> | InsightVizNode<RetentionQuery>
}

// $pageview covers web, $screen covers mobile apps — combined so the tile works day one
// regardless of platform, without asking the customer to pick one first.
function activityEvent(math: MathType, mathProperty?: string): GroupNode {
    const series: EventsNode[] = [
        { kind: NodeKind.EventsNode, event: '$pageview' },
        { kind: NodeKind.EventsNode, event: '$screen' },
    ]
    return {
        kind: NodeKind.GroupNode,
        operator: FilterLogicalOperator.Or,
        nodes: series,
        math,
        math_property: mathProperty,
    }
}

export function getHomeTabInterval(dateRange: DateRange): IntervalType {
    const dateFrom = dateRange.date_from
    const dateTo = dateRange.date_to
    const preset = dateMapping.find(({ values }) => values[0] === dateFrom && (values[1] ?? null) === (dateTo ?? null))
    if (preset?.defaultInterval) {
        return preset.defaultInterval
    }

    const minuteRange = dateFrom?.match(/^-(\d+)M$/)
    if (minuteRange) {
        return 'minute'
    }
    const hourRange = dateFrom?.match(/^-(\d+)h$/)
    if (hourRange) {
        return Number(hourRange[1]) <= 1 ? 'minute' : Number(hourRange[1]) <= 48 ? 'hour' : 'day'
    }
    const dayRange = dateFrom?.match(/^-(\d+)d$/)
    if (dayRange) {
        return Number(dayRange[1]) <= 2 ? 'hour' : 'day'
    }

    if (dateFrom?.match(/^\d{4}-\d{2}-\d{2}(?:T|$)/)) {
        const durationMs = Date.parse(dateTo ?? new Date().toISOString()) - Date.parse(dateFrom)
        if (durationMs > 0 && durationMs <= 60 * 60 * 1000) {
            return 'minute'
        }
        if (durationMs > 0 && durationMs <= 48 * 60 * 60 * 1000) {
            return 'hour'
        }
        if (durationMs > 0) {
            return getDefaultInterval(dateFrom, dateTo ?? new Date().toISOString())
        }
    }
    return 'day'
}

function getHomeTabRetentionIntervals(dateRange: DateRange): number {
    const dateFrom = dateRange.date_from
    const relative = dateFrom?.match(/^-(\d+)([hdwm])$/)
    const unitDays: Record<string, number> = { h: 1 / 24, d: 1, w: 7, m: 30 }
    const rangeDays = relative
        ? Number(relative[1]) * unitDays[relative[2]]
        : dateFrom && /^\d{4}-\d{2}-\d{2}/.test(dateFrom)
          ? (Date.parse(dateRange.date_to ?? new Date().toISOString()) - Date.parse(dateFrom)) / 86_400_000
          : 30

    return Math.min(12, Math.max(2, Math.ceil(rangeDays / 7) + 1))
}

function trendsQuery(series: GroupNode | EventsNode, dateRange: DateRange, compare: boolean): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [series],
        interval: getHomeTabInterval(dateRange),
        dateRange,
        compareFilter: { compare },
    }
}

function statQuery(
    key: HomeTabMetricKey,
    title: string,
    kind: WebAnalyticsItemKind,
    series: GroupNode,
    dateRange: DateRange,
    compare: boolean,
    isIncreaseBad?: boolean
): HomeTabStatQuery {
    return {
        key,
        title,
        kind,
        isIncreaseBad,
        trendQuery: trendsQuery(series, dateRange, false),
        query: {
            ...trendsQuery(series, dateRange, compare),
            trendsFilter: { display: ChartDisplayType.BoldNumber },
        },
    }
}

function chartOption(
    key: string,
    title: string,
    description: string,
    series: GroupNode,
    dateRange: DateRange,
    compare: boolean,
    interval?: IntervalType
): HomeTabChartOption {
    return {
        key,
        title,
        description,
        query: {
            kind: NodeKind.InsightVizNode,
            embedded: true,
            source: {
                ...trendsQuery(series, dateRange, compare),
                ...(interval ? { interval } : {}),
            },
        },
    }
}

export function getHomeTabStatValue(stat: HomeTabStatQuery, result?: TrendResult): number | null | undefined {
    if (stat.summary === 'daily_average') {
        return result?.data?.length
            ? result.data.reduce((total, value) => total + value, 0) / result.data.length
            : undefined
    }
    return result?.aggregated_value
}

export function isHomeTabStatBucketInProgress(
    result: TrendResult | undefined,
    interval: IntervalType,
    timezone: string,
    weekStartDay?: number | null,
    now: dayjs.Dayjs = dayjs()
): boolean {
    const buckets = result?.days.map(normalizeBucket) ?? []
    if (interval === 'week') {
        const currentBucket = startOfWeek(now.tz(timezone), weekStartDay).format(BUCKET_FORMAT)
        return buckets.length >= 2 && buckets[buckets.length - 1] === currentBucket
    }
    return lastBucketIsInProgress(buckets, timezone, interval, now)
}

/** Summary metrics for the compact tile row. */
export function getHomeTabStatQueries(dateRange: DateRange, compare: boolean): HomeTabStatQuery[] {
    const dailyActiveUsers: HomeTabStatQuery = {
        key: 'daily_active_users',
        title: 'Avg. DAU',
        kind: 'unit',
        summary: 'daily_average',
        description:
            'Average daily unique people with a page or screen view in the selected period, including days with no activity.',
        query: {
            ...trendsQuery(activityEvent(BaseMathType.UniqueUsers), dateRange, compare),
            interval: 'day',
            trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
        },
    }
    const activeUsers = statQuery(
        'active_users',
        'Active users',
        'unit',
        activityEvent(BaseMathType.UniqueUsers),
        dateRange,
        compare
    )
    return [
        {
            ...activeUsers,
            ...(activeUsers.query.interval === 'day'
                ? { trendQuery: dailyActiveUsers.query, trendKey: dailyActiveUsers.key }
                : {}),
        },
        statQuery('sessions', 'Sessions', 'unit', activityEvent(BaseMathType.UniqueSessions), dateRange, compare),
        statQuery(
            'new_users',
            'First-time users',
            'unit',
            activityEvent(BaseMathType.FirstTimeForUser),
            dateRange,
            compare
        ),
        statQuery(
            'session_duration',
            'Session duration',
            'duration_s',
            activityEvent(PropertyMathType.Average, '$session_duration'),
            dateRange,
            compare
        ),
        dailyActiveUsers,
    ]
}

/** The full set of charts the chart picker can show, one at a time. */
export function getHomeTabChartOptions(dateRange: DateRange, compare: boolean): HomeTabChartOption[] {
    const interval = getHomeTabInterval(dateRange)
    const intervalNoun: Record<IntervalType, string> = {
        second: 'second',
        minute: 'minute',
        hour: 'hour',
        day: 'day',
        week: 'week',
        month: 'month',
        quarter: 'quarter',
        year: 'year',
    }
    const bucket = intervalNoun[interval]

    return [
        chartOption(
            'daily_active_users',
            'Daily active users',
            'Unique people who viewed a page or screen each day. The tile shows the daily average for this period.',
            activityEvent(BaseMathType.UniqueUsers),
            dateRange,
            compare,
            'day'
        ),
        chartOption(
            'active_users',
            'Active users',
            `Unique people who viewed a page or screen each ${bucket}.`,
            activityEvent(BaseMathType.UniqueUsers),
            dateRange,
            compare
        ),
        chartOption(
            'sessions',
            'Sessions',
            `Distinct sessions with a page or screen view each ${bucket}.`,
            activityEvent(BaseMathType.UniqueSessions),
            dateRange,
            compare
        ),
        chartOption(
            'weekly_active_users',
            'Weekly active users',
            'Unique people active in the trailing 7 days, trended daily.',
            activityEvent(BaseMathType.WeeklyActiveUsers),
            dateRange,
            compare,
            'day'
        ),
        chartOption(
            'new_users',
            'First-time users',
            `People with their first observed page or screen view each ${bucket}.`,
            activityEvent(BaseMathType.FirstTimeForUser),
            dateRange,
            compare
        ),
        chartOption(
            'session_duration',
            'Avg. session duration',
            `Average duration of observed sessions each ${bucket}.`,
            activityEvent(PropertyMathType.Average, '$session_duration'),
            dateRange,
            compare
        ),
        {
            key: 'retention',
            title: 'New user retention',
            description: 'Compare weekly cohorts of first-time visitors and see when they return.',
            query: {
                kind: NodeKind.InsightVizNode,
                embedded: true,
                source: {
                    kind: NodeKind.RetentionQuery,
                    dateRange,
                    retentionFilter: {
                        period: RetentionPeriod.Week,
                        totalIntervals: getHomeTabRetentionIntervals(dateRange),
                        dashboardDisplay: RetentionDashboardDisplayType.TableOnly,
                        retentionType: RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS,
                        targetEntity: {
                            type: 'events',
                            properties: [
                                {
                                    type: PropertyFilterType.EventMetadata,
                                    key: 'event',
                                    operator: PropertyOperator.In,
                                    value: ['$pageview', '$screen'],
                                },
                            ],
                        },
                        returningEntity: {
                            type: 'events',
                            properties: [
                                {
                                    type: PropertyFilterType.EventMetadata,
                                    key: 'event',
                                    operator: PropertyOperator.In,
                                    value: ['$pageview', '$screen'],
                                },
                            ],
                        },
                    },
                },
            },
        },
    ]
}

export function getHomeTabAudienceOptions(dateRange: DateRange): HomeTabChartOption[] {
    return [
        {
            key: 'users_by_country',
            title: 'Active users by country',
            description: 'Where people use your product, based on IP geolocation.',
            query: {
                kind: NodeKind.InsightVizNode,
                embedded: true,
                source: {
                    ...trendsQuery(activityEvent(BaseMathType.UniqueUsers), dateRange, false),
                    trendsFilter: { display: ChartDisplayType.WorldMap },
                    breakdownFilter: {
                        breakdown: '$geoip_country_code',
                        breakdown_type: 'event',
                        breakdown_limit: 250,
                        breakdown_hide_other_aggregation: true,
                    },
                },
            },
        },
        {
            key: 'sessions_by_device',
            title: 'Sessions by device',
            description: 'See the mix of desktop, mobile, and tablet sessions.',
            query: {
                kind: NodeKind.InsightVizNode,
                embedded: true,
                source: {
                    ...trendsQuery(activityEvent(BaseMathType.UniqueSessions), dateRange, false),
                    trendsFilter: {
                        display: ChartDisplayType.ActionsDonut,
                        showLegend: true,
                        legendPosition: 'bottom',
                    },
                    breakdownFilter: {
                        breakdown: '$device_type',
                        breakdown_type: 'event',
                        breakdown_limit: 8,
                    },
                },
            },
        },
    ]
}

function rankedBreakdownOption(
    key: string,
    title: string,
    description: string,
    event: string | null,
    breakdown: string,
    breakdownType: 'event' | 'event_metadata',
    dateRange: DateRange
): HomeTabChartOption {
    return {
        key,
        title,
        description,
        query: {
            kind: NodeKind.InsightVizNode,
            embedded: true,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event, math: BaseMathType.TotalCount }],
                dateRange,
                interval: getHomeTabInterval(dateRange),
                trendsFilter: { display: ChartDisplayType.ActionsBarValue },
                breakdownFilter: {
                    breakdown,
                    breakdown_type: breakdownType,
                    breakdown_limit: 8,
                    breakdown_hide_other_aggregation: true,
                },
            },
        },
    }
}

export function getHomeTabBreakdownOptions(dateRange: DateRange): HomeTabChartOption[] {
    return [
        rankedBreakdownOption(
            'top_pages',
            'Top pages',
            'Pages with the most views.',
            '$pageview',
            '$pathname',
            'event',
            dateRange
        ),
        rankedBreakdownOption(
            'top_screens',
            'Top screens',
            'Screens with the most views.',
            '$screen',
            '$screen_name',
            'event',
            dateRange
        ),
        rankedBreakdownOption(
            'top_events',
            'Top events',
            'The most frequent event names in this period.',
            null,
            'event',
            'event_metadata',
            dateRange
        ),
    ]
}

/** A metric tile as an insight. The tile averages daily points in React, so that summary moves into the query. */
export function getHomeTabStatInsightQuery(stat: HomeTabStatQuery): InsightVizNode<TrendsQuery> {
    return {
        kind: NodeKind.InsightVizNode,
        source:
            stat.summary === 'daily_average'
                ? {
                      ...stat.query,
                      trendsFilter: {
                          ...stat.query.trendsFilter,
                          display: ChartDisplayType.Metric,
                          metricSummary: 'average',
                      },
                  }
                : stat.query,
    }
}

export function getHomeTabExploreUrl(query: HomeTabChartOption['query']): string {
    const insightQuery: HomeTabChartOption['query'] = { ...query, embedded: undefined }
    return urls.insightNew({ query: insightQuery })
}

interface HomeTabDashboardTile {
    name: string
    description: string
    source: TrendsQuery | RetentionQuery
    w: number
    h: number
}

// The Metric display (number with a sparkline) sums the interval points, which counts a person once per
// active day. Weekly active users on the latest day counts each person once and still has a daily trend.
const HOME_TAB_STAT_METRIC_SUMMARIES: Record<HomeTabMetricKey, 'total' | 'average' | 'latest'> = {
    active_users: 'latest',
    sessions: 'total',
    new_users: 'total',
    session_duration: 'average',
    daily_active_users: 'average',
}

const HOME_TAB_STAT_DASHBOARD_NAMES: Partial<Record<HomeTabMetricKey, string>> = {
    active_users: 'Weekly active users',
    session_duration: 'Avg. session duration',
}

/** PostHog Home as a dashboard template, so a copy keeps the Home charts and the user can edit them. */
export function getHomeTabDashboardTemplate(): DashboardTemplateType {
    const dateRange = HOME_TAB_DEFAULT_DATE_RANGE
    const compare = true
    const charts = new Map(
        [
            ...getHomeTabChartOptions(dateRange, compare),
            ...getHomeTabBreakdownOptions(dateRange),
            ...getHomeTabAudienceOptions(dateRange),
        ].map((option) => [option.key, option])
    )
    const chartTile = (key: string, w: number, h: number): HomeTabDashboardTile => {
        const chart = charts.get(key)
        if (!chart) {
            throw new Error(`Home chart ${key} does not exist`)
        }
        return { name: chart.title, description: chart.description, source: chart.query.source, w, h }
    }
    // A 12-column row holds four equal metric tiles, and the full-width Daily active users chart already shows Avg. DAU.
    const statQueries = getHomeTabStatQueries(dateRange, compare).filter(({ key }) => key !== 'daily_active_users')
    const statTiles = statQueries.map((stat): HomeTabDashboardTile => {
        const weeklyActiveUsers = stat.key === 'active_users'
        return {
            name: HOME_TAB_STAT_DASHBOARD_NAMES[stat.key] ?? stat.title,
            description: '',
            source: {
                ...stat.query,
                ...(weeklyActiveUsers
                    ? {
                          series: [activityEvent(BaseMathType.WeeklyActiveUsers)],
                          interval: 'day',
                          compareFilter: { compare: false },
                      }
                    : {}),
                trendsFilter: {
                    ...stat.query.trendsFilter,
                    display: ChartDisplayType.Metric,
                    metricSummary: HOME_TAB_STAT_METRIC_SUMMARIES[stat.key],
                    ...(stat.kind === 'duration_s' ? { aggregationAxisFormat: 'duration' } : {}),
                },
            },
            w: 3,
            h: 2,
        }
    })
    const rows: HomeTabDashboardTile[][] = [
        statTiles,
        [chartTile('daily_active_users', 12, 3)],
        [chartTile('top_pages', 6, 5), chartTile('top_screens', 6, 5)],
        [chartTile('top_events', 6, 5), chartTile('retention', 6, 5)],
        [chartTile('users_by_country', 8, 6), chartTile('sessions_by_device', 4, 6)],
    ]

    const tiles: DashboardTemplateStoredInsightTile[] = []
    let y = 0
    let stackedY = 0
    for (const row of rows) {
        let x = 0
        for (const { name, description, source, w, h } of row) {
            tiles.push({
                type: 'INSIGHT',
                name,
                description,
                query: { kind: NodeKind.InsightVizNode, source },
                layouts: { sm: { x, y, w, h }, xs: { x: 0, y: stackedY, w: 1, h } },
            })
            x += w
            stackedY += h
        }
        y += Math.max(...row.map(({ h }) => h))
    }

    return {
        id: 'product-analytics-home',
        template_name: 'My product analytics Home',
        dashboard_description: 'A copy of the default product analytics dashboard. You can edit, add, or remove tiles.',
        dashboard_filters: {},
        tiles,
        variables: [],
        tags: [],
    }
}
