import { RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS, RETENTION_RECURRING } from 'lib/constants'

import { DateRange, EventsNode, NodeKind } from '~/queries/schema/schema-general'
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

import type { HomeTabViewKey } from './homeTabDefaultLogic'
import {
    activityEvent,
    getHomeTabChartOptions,
    getHomeTabInterval,
    rankedBreakdownOption,
    retentionChartOption,
    trendsQuery,
    type HomeTabAnyChartOption,
    type HomeTabChartOption,
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

function getNewUsersRows(dateRange: DateRange, compare: boolean): HomeTabViewRows {
    return [
        [
            {
                option: overviewChart(dateRange, compare, 'new_users'),
                size: 'primary',
                source: 'Pageviews and screen views',
            },
        ],
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
                                { kind: NodeKind.EventsNode, event: '$identify', custom_name: 'Identified' },
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
        [
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
        ],
    ]
}

function getEngagementRows(dateRange: DateRange): HomeTabViewRows {
    const interval = getHomeTabHourOrLongerInterval(dateRange)
    return [
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
        ],
        [
            {
                option: {
                    key: 'custom_events_over_time',
                    title: 'Custom events over time',
                    description: `Unique people who did each of your top 5 custom events each ${getHomeTabInterval(dateRange)}.`,
                    query: {
                        kind: NodeKind.InsightVizNode,
                        embedded: true,
                        source: {
                            ...trendsQuery(
                                {
                                    kind: NodeKind.EventsNode,
                                    event: null,
                                    math: BaseMathType.UniqueUsers,
                                    properties: CUSTOM_EVENT_FILTERS,
                                },
                                dateRange,
                                false
                            ),
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
                                { ...activityEvent(BaseMathType.UniqueUsers), custom_name: 'Daily active users' },
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
            {
                option: {
                    key: 'stickiness',
                    title: 'How often people come back',
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
    ]
}

function getRetentionRows(dateRange: DateRange): HomeTabViewRows {
    return [
        [
            {
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
            },
        ],
        [
            {
                option: retentionChartOption(
                    'all_user_retention',
                    'Retention of all active users',
                    'Weekly cohorts of everyone active that week, new users included, and the share who were active again in later weeks.',
                    dateRange,
                    RetentionPeriod.Week,
                    RETENTION_RECURRING
                ),
                size: 'supporting',
                source: 'Pageviews and screen views',
            },
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
    ]
}

/** The charts of each Home view except the overview, which has its own layout. */
export function getHomeTabViewRows(
    view: Exclude<HomeTabViewKey, 'overview'>,
    dateRange: DateRange,
    compare: boolean
): HomeTabViewRows {
    switch (view) {
        case 'new_users':
            return getNewUsersRows(dateRange, compare)
        case 'engagement':
            return getEngagementRows(dateRange)
        case 'retention':
            return getRetentionRows(dateRange)
    }
}
