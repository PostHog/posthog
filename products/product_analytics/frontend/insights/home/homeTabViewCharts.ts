import { RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS, RETENTION_RECURRING } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import { DateRange, EventsNode, NodeKind, RetentionResult } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    BaseMathType,
    ChartDisplayType,
    FunnelConversionWindowTimeUnit,
    FunnelMathType,
    FunnelVizType,
    IntervalType,
    PropertyFilterType,
    PropertyOperator,
    RetentionPeriod,
    SurveyEventName,
} from '~/types'

import type { HomeTabMetricKey, HomeTabViewKey } from './homeTabDefaultLogic'
import {
    activityEvent,
    chartOption,
    getHomeTabChartOptions,
    getHomeTabInterval,
    getHomeTabStatQueries,
    rankedBreakdownOption,
    retentionChartOption,
    statQuery,
    trendsQuery,
    type HomeTabAnyChartOption,
    type HomeTabChartOption,
    type HomeTabStatQuery,
} from './homeTabDefaultTiles'

export interface HomeTabViewChart {
    option: HomeTabAnyChartOption
    size: 'primary' | 'supporting' | 'ranking'
    source: string
}

/** A view is a list of rows. A row with one chart is full width, and a row with two charts splits in half. */
export type HomeTabViewRows = HomeTabViewChart[][]

// PostHog SDKs send these without a `$` prefix, so they look like custom events but are not product features.
const SDK_EVENTS = [
    'Application Opened',
    'Application Backgrounded',
    'Application Installed',
    'Application Updated',
    'Application Became Active',
    'Deep Link Opened',
    ...Object.values(SurveyEventName),
]

// PostHog's own events start with `$`, so the remaining events are the ones the customer sends for their features.
const CUSTOM_EVENT_FILTERS: AnyPropertyFilter[] = [
    { type: PropertyFilterType.EventMetadata, key: 'event', operator: PropertyOperator.NotRegex, value: '^\\$' },
    { type: PropertyFilterType.EventMetadata, key: 'event', operator: PropertyOperator.IsNot, value: SDK_EVENTS },
]

const PAGE_OR_SCREEN_FILTER: AnyPropertyFilter = {
    type: PropertyFilterType.EventMetadata,
    key: 'event',
    operator: PropertyOperator.In,
    value: ['$pageview', '$screen'],
}

// Lifecycle, stickiness and funnel steps do not accept a group of events, so the page and screen events are a filter.
const PAGE_OR_SCREEN_EVENTS: EventsNode = {
    kind: NodeKind.EventsNode,
    event: null,
    name: 'Page or screen views',
    properties: [PAGE_OR_SCREEN_FILTER],
}

const SQL_SDK_EVENTS = `(${SDK_EVENTS.map((event) => `'${event}'`).join(', ')})`
const SQL_CUSTOM_EVENT = `NOT startsWith(event, '$') AND event NOT IN ${SQL_SDK_EVENTS}`

// A minute is too short for a person to go dormant and come back, so lifecycle and stickiness use hours at least.
function getHomeTabHourOrLongerInterval(dateRange: DateRange): IntervalType {
    const interval = getHomeTabInterval(dateRange)
    if (interval === 'second' || interval === 'minute') {
        return 'hour'
    }
    if (interval === 'quarter' || interval === 'year') {
        return 'month'
    }
    return interval
}

function overviewChart(dateRange: DateRange, compare: boolean, key: string): HomeTabChartOption {
    const chart = getHomeTabChartOptions(dateRange, compare).find((option) => option.key === key)
    if (!chart) {
        throw new Error(`Home chart ${key} does not exist`)
    }
    return chart
}

function overviewStat(dateRange: DateRange, compare: boolean, key: HomeTabMetricKey): HomeTabStatQuery {
    const stat = getHomeTabStatQueries(dateRange, compare).find((option) => option.key === key)
    if (!stat) {
        throw new Error(`Home stat ${key} does not exist`)
    }
    return stat
}

function describedStat(stat: HomeTabStatQuery, description: string): HomeTabStatQuery {
    return { ...stat, description }
}

export interface HomeTabRetentionSummary {
    value: number
    trend: number[]
    labels: string[]
}

/** Retention at one interval across the cohorts that had the full interval to come back, weighted by cohort size. */
export function getHomeTabRetentionSummary(
    results: RetentionResult[] | undefined,
    interval: number,
    period: 'day' | 'week',
    now: dayjs.Dayjs = dayjs()
): HomeTabRetentionSummary | null {
    const complete = (results ?? []).filter(
        (cohort) =>
            cohort.values.length > interval &&
            cohort.values[0].count > 0 &&
            !dayjs(cohort.date)
                .add(interval + 1, period)
                .isAfter(now)
    )
    if (!complete.length) {
        return null
    }
    const returned = complete.reduce((total, cohort) => total + cohort.values[interval].count, 0)
    const size = complete.reduce((total, cohort) => total + cohort.values[0].count, 0)
    return {
        value: (100 * returned) / size,
        trend: complete.map((cohort) => (100 * cohort.values[interval].count) / cohort.values[0].count),
        labels: complete.map((cohort) => cohort.date),
    }
}

export interface HomeTabRetentionStat {
    key: string
    title: string
    description: string
    interval: number
    period: 'day' | 'week'
    /** The cohort table that also shows in a section, so the tile and the table share one query. */
    table: HomeTabChartOption
    chart: HomeTabViewChart
}

export type HomeTabViewHeadlines =
    | { kind: 'trend'; stats: HomeTabStatQuery[]; charts: Partial<Record<HomeTabMetricKey, HomeTabViewChart>> }
    | { kind: 'retention'; stats: HomeTabRetentionStat[] }

export interface HomeTabViewSection {
    title: string
    rows: HomeTabViewRows
}

/** A view reads top to bottom: headline tiles, the trend of the selected tile, then sections that explain it. */
export interface HomeTabViewLayout {
    headlines: HomeTabViewHeadlines
    sections: HomeTabViewSection[]
}

function getNewUsersLayout(dateRange: DateRange, compare: boolean): HomeTabViewLayout {
    const bucket = getHomeTabInterval(dateRange)
    const identified: EventsNode = {
        kind: NodeKind.EventsNode,
        event: '$identify',
        math: BaseMathType.FirstTimeForUser,
    }
    const activated: EventsNode = {
        kind: NodeKind.EventsNode,
        event: null,
        math: BaseMathType.FirstMatchingEventForUser,
        properties: CUSTOM_EVENT_FILTERS,
    }
    return {
        headlines: {
            kind: 'trend',
            stats: [
                overviewStat(dateRange, compare, 'new_users'),
                describedStat(
                    statQuery('identified_users', 'Newly identified', 'unit', identified, dateRange, compare),
                    'People identified for the first time, for example when they sign up or first log in.'
                ),
                describedStat(
                    statQuery('activated_users', 'Activated users', 'unit', activated, dateRange, compare),
                    'People who did their first custom event in this period.'
                ),
            ],
            charts: {
                new_users: {
                    option: overviewChart(dateRange, compare, 'new_users'),
                    size: 'primary',
                    source: 'Pageviews and screen views',
                },
                identified_users: {
                    option: chartOption(
                        'identified_users',
                        'Newly identified',
                        `People identified for the first time each ${bucket}.`,
                        identified,
                        dateRange,
                        compare
                    ),
                    size: 'primary',
                    source: 'Identify calls',
                },
                activated_users: {
                    option: chartOption(
                        'activated_users',
                        'Activated users',
                        `People who did their first custom event each ${bucket}.`,
                        activated,
                        dateRange,
                        compare
                    ),
                    size: 'primary',
                    source: 'Custom events',
                },
            },
        },
        sections: [
            {
                title: 'How new users activate',
                rows: [
                    [
                        {
                            option: {
                                key: 'new_user_activation',
                                title: 'New user activation',
                                description:
                                    'First-time users who were identified, then did a custom event, within 7 days of their first page or screen view.',
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    embedded: true,
                                    source: {
                                        kind: NodeKind.FunnelsQuery,
                                        dateRange,
                                        series: [
                                            {
                                                ...PAGE_OR_SCREEN_EVENTS,
                                                custom_name: 'First page or screen view',
                                                math: FunnelMathType.FirstTimeForUserWithFilters,
                                            },
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: '$identify',
                                                custom_name: 'Identified',
                                            },
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: null,
                                                custom_name: 'Any custom event',
                                                properties: CUSTOM_EVENT_FILTERS,
                                            },
                                        ],
                                        funnelsFilter: {
                                            funnelVizType: FunnelVizType.Steps,
                                            funnelWindowInterval: 7,
                                            funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
                                        },
                                    },
                                },
                            },
                            size: 'supporting',
                            source: 'Pageviews, screen views, identify calls and custom events',
                        },
                    ],
                ],
            },
            {
                title: 'What new users do next',
                rows: [
                    [
                        {
                            option: rankedBreakdownOption(
                                'first_custom_events',
                                'First custom event',
                                'People whose first custom event happened in this period, by which event it was.',
                                {
                                    event: null,
                                    breakdown: 'event',
                                    breakdownType: 'event_metadata',
                                    math: BaseMathType.FirstMatchingEventForUser,
                                    properties: CUSTOM_EVENT_FILTERS,
                                },
                                dateRange
                            ),
                            size: 'supporting',
                            source: 'Custom events',
                        },
                        {
                            option: retentionChartOption(
                                'new_user_daily_retention',
                                'New user retention in the first week',
                                'The share of first-time users who come back on each of their first 7 days.',
                                dateRange,
                                RetentionPeriod.Day,
                                RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS
                            ),
                            size: 'supporting',
                            source: 'Pageviews and screen views',
                        },
                    ],
                ],
            },
        ],
    }
}

function getEngagementLayout(dateRange: DateRange, compare: boolean): HomeTabViewLayout {
    const bucket = getHomeTabInterval(dateRange)
    const interval = getHomeTabHourOrLongerInterval(dateRange)
    const sessionsPerUserSeries = [activityEvent(BaseMathType.UniqueSessions), activityEvent(BaseMathType.UniqueUsers)]
    const customEventUsers: EventsNode = {
        kind: NodeKind.EventsNode,
        event: null,
        math: BaseMathType.UniqueUsers,
        properties: CUSTOM_EVENT_FILTERS,
    }
    return {
        headlines: {
            kind: 'trend',
            stats: [
                overviewStat(dateRange, compare, 'active_users'),
                overviewStat(dateRange, compare, 'daily_active_users'),
                {
                    key: 'sessions_per_user',
                    title: 'Sessions per user',
                    kind: 'unit',
                    description: 'Sessions divided by active users in this period.',
                    query: {
                        ...trendsQuery(sessionsPerUserSeries[0], dateRange, compare),
                        series: sessionsPerUserSeries,
                        trendsFilter: { display: ChartDisplayType.BoldNumber, formula: 'A/B' },
                    },
                    trendQuery: {
                        ...trendsQuery(sessionsPerUserSeries[0], dateRange, false),
                        series: sessionsPerUserSeries,
                        trendsFilter: { formula: 'A/B' },
                    },
                },
                describedStat(
                    statQuery('custom_event_users', 'Custom event users', 'unit', customEventUsers, dateRange, compare),
                    'Unique people who did at least one custom event.'
                ),
            ],
            charts: {
                active_users: {
                    option: overviewChart(dateRange, compare, 'active_users'),
                    size: 'primary',
                    source: 'Pageviews and screen views',
                },
                daily_active_users: {
                    option: overviewChart(dateRange, compare, 'daily_active_users'),
                    size: 'primary',
                    source: 'Pageviews and screen views',
                },
                sessions_per_user: {
                    option: {
                        key: 'sessions_per_user',
                        title: 'Sessions per user',
                        description: `Sessions divided by active users each ${bucket}.`,
                        query: {
                            kind: NodeKind.InsightVizNode,
                            embedded: true,
                            source: {
                                ...trendsQuery(sessionsPerUserSeries[0], dateRange, compare),
                                series: sessionsPerUserSeries,
                                trendsFilter: { display: ChartDisplayType.ActionsLineGraph, formula: 'A/B' },
                            },
                        },
                    },
                    size: 'primary',
                    source: 'Pageviews and screen views',
                },
                custom_event_users: {
                    option: chartOption(
                        'custom_event_users',
                        'Custom event users',
                        `Unique people who did at least one custom event each ${bucket}.`,
                        customEventUsers,
                        dateRange,
                        compare
                    ),
                    size: 'primary',
                    source: 'Custom events',
                },
            },
        },
        sections: [
            {
                title: 'How often people come back',
                rows: [
                    [
                        {
                            option: {
                                key: 'stickiness',
                                title: 'Days active',
                                description: `The number of people active on 1, 2, 3 or more ${interval}s in this period.`,
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    embedded: true,
                                    source: {
                                        kind: NodeKind.StickinessQuery,
                                        series: [{ ...PAGE_OR_SCREEN_EVENTS, math: BaseMathType.UniqueUsers }],
                                        interval,
                                        dateRange,
                                        stickinessFilter: { display: ChartDisplayType.ActionsBar },
                                    },
                                },
                            },
                            size: 'supporting',
                            source: 'Pageviews and screen views',
                        },
                        {
                            option: {
                                key: 'dau_mau_ratio',
                                title: 'Daily to monthly active users',
                                description:
                                    'Daily active users as a share of monthly active users. A higher share means people come back more often.',
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    embedded: true,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            activityEvent(BaseMathType.UniqueUsers),
                                            activityEvent(BaseMathType.MonthlyActiveUsers),
                                        ],
                                        interval: 'day',
                                        dateRange,
                                        trendsFilter: {
                                            display: ChartDisplayType.ActionsLineGraph,
                                            formula: 'A/B',
                                            aggregationAxisFormat: 'percentage_scaled',
                                        },
                                    },
                                },
                            },
                            size: 'supporting',
                            source: 'Pageviews and screen views',
                        },
                    ],
                    [
                        {
                            option: {
                                key: 'daily_weekly_monthly_active_users',
                                title: 'Daily, weekly, and monthly active users',
                                description:
                                    'Unique people active on each day, in the trailing 7 days, and in the trailing 30 days.',
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    embedded: true,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                ...activityEvent(BaseMathType.UniqueUsers),
                                                custom_name: 'Daily active users',
                                            },
                                            {
                                                ...activityEvent(BaseMathType.WeeklyActiveUsers),
                                                custom_name: 'Weekly active users',
                                            },
                                            {
                                                ...activityEvent(BaseMathType.MonthlyActiveUsers),
                                                custom_name: 'Monthly active users',
                                            },
                                        ],
                                        interval: 'day',
                                        dateRange,
                                        trendsFilter: { display: ChartDisplayType.ActionsLineGraph, showLegend: true },
                                    },
                                },
                            },
                            size: 'supporting',
                            source: 'Pageviews and screen views',
                        },
                    ],
                ],
            },
            {
                title: 'What people use',
                rows: [
                    [
                        {
                            option: {
                                key: 'custom_event_adoption',
                                title: 'Custom event adoption',
                                description:
                                    'The share of active people who did each of your custom events. Active people viewed a page or screen, or did a custom event.',
                                query: {
                                    kind: NodeKind.DataVisualizationNode,
                                    source: {
                                        kind: NodeKind.HogQLQuery,
                                        query: `WITH active AS (
    SELECT uniq(person_id) AS people
    FROM events
    WHERE {filters} AND (event IN ('$pageview', '$screen') OR (${SQL_CUSTOM_EVENT}))
)
SELECT event, uniq(person_id) AS people, round(people / (SELECT people FROM active), 3) AS share
FROM events
WHERE {filters} AND ${SQL_CUSTOM_EVENT}
GROUP BY event
ORDER BY share DESC
LIMIT 8`,
                                        filters: { dateRange },
                                    },
                                    display: ChartDisplayType.ActionsTable,
                                    tableSettings: {
                                        columns: [
                                            { column: 'event', settings: { display: { label: 'Custom event' } } },
                                            { column: 'people', settings: { display: { label: 'People' } } },
                                            {
                                                column: 'share',
                                                settings: {
                                                    display: { label: 'Share of active people' },
                                                    formatting: { style: 'percent', decimalPlaces: 1 },
                                                },
                                            },
                                        ],
                                    },
                                },
                            },
                            size: 'supporting',
                            source: 'Pageviews, screen views and custom events',
                        },
                        {
                            option: {
                                key: 'custom_events_over_time',
                                title: 'Custom events over time',
                                description: `Unique people who did each of your top 5 custom events each ${bucket}.`,
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    embedded: true,
                                    source: {
                                        ...trendsQuery({ ...customEventUsers }, dateRange, false),
                                        trendsFilter: { display: ChartDisplayType.ActionsLineGraph, showLegend: true },
                                        breakdownFilter: {
                                            breakdown: 'event',
                                            breakdown_type: 'event_metadata',
                                            breakdown_limit: 5,
                                            breakdown_hide_other_aggregation: true,
                                        },
                                    },
                                },
                            },
                            size: 'supporting',
                            source: 'Custom events',
                        },
                    ],
                    [
                        {
                            option: rankedBreakdownOption(
                                'top_clicked_elements',
                                'Most clicked elements',
                                'Elements that the most people clicked or tapped, grouped by element text.',
                                {
                                    event: '$autocapture',
                                    breakdown: '$el_text',
                                    breakdownType: 'event',
                                    math: BaseMathType.UniqueUsers,
                                    properties: [
                                        {
                                            type: PropertyFilterType.Event,
                                            key: '$event_type',
                                            operator: PropertyOperator.Exact,
                                            value: ['click', 'touch'],
                                        },
                                    ],
                                },
                                dateRange
                            ),
                            size: 'ranking',
                            source: 'Autocaptured clicks and taps',
                        },
                    ],
                ],
            },
        ],
    }
}

function getRetentionLayout(dateRange: DateRange, compare: boolean): HomeTabViewLayout {
    const newUserTable = overviewChart(dateRange, compare, 'retention')
    const allUserTable = retentionChartOption(
        'all_user_retention',
        'Retention of all active users',
        'Weekly cohorts of everyone active that week, new users included, and the share who were active again in later weeks.',
        dateRange,
        RetentionPeriod.Week,
        RETENTION_RECURRING
    )
    const newUserCurve: HomeTabViewChart = {
        option: retentionChartOption(
            'new_user_retention_curve',
            'New user retention',
            'The share of first-time users who come back in each week after their first visit. Shows at least 8 weeks.',
            dateRange,
            RetentionPeriod.Week,
            RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS,
            'curve'
        ),
        size: 'primary',
        source: 'Pageviews and screen views',
    }
    const allUserCurve: HomeTabViewChart = {
        option: retentionChartOption(
            'all_user_retention_curve',
            'Retention of all active users',
            'The share of everyone active in a week who is active again in each later week. Shows at least 8 weeks.',
            dateRange,
            RetentionPeriod.Week,
            RETENTION_RECURRING,
            'curve'
        ),
        size: 'primary',
        source: 'Pageviews and screen views',
    }
    const COMPLETE_NOTE = 'Only cohorts that had the full week to come back count.'
    return {
        headlines: {
            kind: 'retention',
            stats: [
                {
                    key: 'new_user_week_1',
                    title: 'New users, week 1',
                    description: `The share of first-time users who came back in the week after their first visit. ${COMPLETE_NOTE}`,
                    interval: 1,
                    period: 'week',
                    table: newUserTable,
                    chart: newUserCurve,
                },
                {
                    key: 'new_user_week_4',
                    title: 'New users, week 4',
                    description: `The share of first-time users who were active 4 weeks after their first visit. ${COMPLETE_NOTE}`,
                    interval: 4,
                    period: 'week',
                    table: newUserTable,
                    chart: newUserCurve,
                },
                {
                    key: 'all_user_week_1',
                    title: 'All users, week 1',
                    description: `The share of everyone active in a week who was active again the next week. ${COMPLETE_NOTE}`,
                    interval: 1,
                    period: 'week',
                    table: allUserTable,
                    chart: allUserCurve,
                },
                {
                    key: 'all_user_week_4',
                    title: 'All users, week 4',
                    description: `The share of everyone active in a week who was active again 4 weeks later. ${COMPLETE_NOTE}`,
                    interval: 4,
                    period: 'week',
                    table: allUserTable,
                    chart: allUserCurve,
                },
            ],
        },
        sections: [
            {
                title: 'Retention by cohort',
                rows: [
                    [
                        { option: newUserTable, size: 'supporting', source: 'Pageviews and screen views' },
                        { option: allUserTable, size: 'supporting', source: 'Pageviews and screen views' },
                    ],
                ],
            },
            {
                title: 'How your active users change',
                rows: [
                    [
                        {
                            option: {
                                key: 'lifecycle',
                                title: 'Lifecycle of people with profiles',
                                description:
                                    'People with person profiles, split into new, returning, resurrecting, and dormant. Anonymous visitors are not counted.',
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    embedded: true,
                                    source: {
                                        kind: NodeKind.LifecycleQuery,
                                        series: [PAGE_OR_SCREEN_EVENTS],
                                        interval: getHomeTabHourOrLongerInterval(dateRange),
                                        dateRange,
                                        lifecycleFilter: { showLegend: true },
                                    },
                                },
                            },
                            size: 'supporting',
                            source: 'Pageviews and screen views from people with profiles',
                        },
                    ],
                ],
            },
        ],
    }
}

/** The layout of each Home view except the overview, which has its own layout. */
export function getHomeTabViewLayout(
    view: Exclude<HomeTabViewKey, 'overview'>,
    dateRange: DateRange,
    compare: boolean
): HomeTabViewLayout {
    switch (view) {
        case 'new_users':
            return getNewUsersLayout(dateRange, compare)
        case 'engagement':
            return getEngagementLayout(dateRange, compare)
        case 'retention':
            return getRetentionLayout(dateRange, compare)
    }
}
