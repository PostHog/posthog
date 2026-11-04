import { RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS, RETENTION_RECURRING } from 'lib/constants'

import { DateRange, EventsNode, NodeKind } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    BaseMathType,
    ChartDisplayType,
    IntervalType,
    PropertyFilterType,
    PropertyOperator,
    RetentionPeriod,
} from '~/types'

import type { HomeTabViewKey } from './homeTabDefaultLogic'
import {
    activityEvent,
    getHomeTabChartOptions,
    getHomeTabInterval,
    getHomeTabRetentionIntervals,
    rankedBreakdownOption,
    retentionChartOption,
    trendsQuery,
    type HomeTabChartOption,
} from './homeTabDefaultTiles'

export interface HomeTabViewChart {
    option: HomeTabChartOption
    size: 'primary' | 'supporting' | 'ranking'
    source: string
}

/** A view is a list of rows. A row with one chart is full width, and a row with two charts splits in half. */
export type HomeTabViewRows = HomeTabViewChart[][]

// PostHog's own events start with `$`, so the remaining events are the ones the customer sends for their features.
const CUSTOM_EVENT_FILTER: AnyPropertyFilter = {
    type: PropertyFilterType.EventMetadata,
    key: 'event',
    operator: PropertyOperator.NotRegex,
    value: '^\\$',
}

// Lifecycle and stickiness queries do not accept a group of events, so the page and screen events are a filter.
const PAGE_OR_SCREEN_EVENTS: EventsNode = {
    kind: NodeKind.EventsNode,
    event: null,
    name: 'Page or screen views',
    properties: [
        {
            type: PropertyFilterType.EventMetadata,
            key: 'event',
            operator: PropertyOperator.In,
            value: ['$pageview', '$screen'],
        },
    ],
}

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

function getOnboardingRows(dateRange: DateRange, compare: boolean): HomeTabViewRows {
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
                option: rankedBreakdownOption(
                    'new_user_landing_pages',
                    'Where new users land',
                    'The first page each new user viewed in this period.',
                    {
                        event: '$pageview',
                        breakdown: '$pathname',
                        breakdownType: 'event',
                        math: BaseMathType.FirstTimeForUser,
                    },
                    dateRange
                ),
                size: 'ranking',
                source: 'Pageviews',
            },
            {
                option: rankedBreakdownOption(
                    'new_user_referrers',
                    'Where new users come from',
                    'The site that referred each new user to their first page. $direct means no referrer.',
                    {
                        event: '$pageview',
                        breakdown: '$referring_domain',
                        breakdownType: 'event',
                        math: BaseMathType.FirstTimeForUser,
                    },
                    dateRange
                ),
                size: 'ranking',
                source: 'Pageviews',
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
                    8,
                    RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS
                ),
                size: 'supporting',
                source: 'Pageviews and screen views',
            },
        ],
    ]
}

function getFeatureEngagementRows(dateRange: DateRange): HomeTabViewRows {
    const interval = getHomeTabHourOrLongerInterval(dateRange)
    return [
        [
            {
                option: {
                    key: 'custom_events_over_time',
                    title: 'Feature usage over time',
                    description: `Unique people who triggered each of your top 5 custom events each ${getHomeTabInterval(dateRange)}.`,
                    query: {
                        kind: NodeKind.InsightVizNode,
                        embedded: true,
                        source: {
                            ...trendsQuery(
                                {
                                    kind: NodeKind.EventsNode,
                                    event: null,
                                    math: BaseMathType.UniqueUsers,
                                    properties: [CUSTOM_EVENT_FILTER],
                                },
                                dateRange,
                                false
                            ),
                            trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
                            breakdownFilter: {
                                breakdown: 'event',
                                breakdown_type: 'event_metadata',
                                breakdown_limit: 5,
                                breakdown_hide_other_aggregation: true,
                            },
                        },
                    },
                },
                size: 'primary',
                source: 'Custom events',
            },
        ],
        [
            {
                option: rankedBreakdownOption(
                    'top_custom_events',
                    'Most used features',
                    'Custom events ranked by how many people triggered them.',
                    {
                        event: null,
                        breakdown: 'event',
                        breakdownType: 'event_metadata',
                        math: BaseMathType.UniqueUsers,
                        properties: [CUSTOM_EVENT_FILTER],
                    },
                    dateRange
                ),
                size: 'ranking',
                source: 'Custom events',
            },
            {
                option: rankedBreakdownOption(
                    'top_clicked_elements',
                    'Most clicked elements',
                    'Elements ranked by how many people clicked them, by element text.',
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
                                value: 'click',
                            },
                        ],
                    },
                    dateRange
                ),
                size: 'ranking',
                source: 'Autocaptured clicks',
            },
        ],
        [
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
    ]
}

function getRetentionRows(dateRange: DateRange, compare: boolean): HomeTabViewRows {
    return [
        [
            {
                option: {
                    key: 'lifecycle',
                    title: 'Active user lifecycle',
                    description:
                        'Active people split into new, returning, and resurrecting, and the people who became dormant.',
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
                size: 'primary',
                source: 'Pageviews and screen views',
            },
        ],
        [
            {
                option: overviewChart(dateRange, compare, 'retention'),
                size: 'supporting',
                source: 'Pageviews and screen views',
            },
            {
                option: retentionChartOption(
                    'returning_user_retention',
                    'Returning user retention',
                    'Weekly cohorts of all active people, and the share who were active again in later weeks.',
                    dateRange,
                    RetentionPeriod.Week,
                    getHomeTabRetentionIntervals(dateRange),
                    RETENTION_RECURRING
                ),
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
                                activityEvent(BaseMathType.UniqueUsers),
                                activityEvent(BaseMathType.WeeklyActiveUsers),
                                activityEvent(BaseMathType.MonthlyActiveUsers),
                            ],
                            interval: 'day',
                            dateRange,
                            trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
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
    ]
}

/** The charts of each Home view except the overview, which has its own layout. */
export function getHomeTabViewRows(
    view: Exclude<HomeTabViewKey, 'overview'>,
    dateRange: DateRange,
    compare: boolean
): HomeTabViewRows {
    switch (view) {
        case 'onboarding':
            return getOnboardingRows(dateRange, compare)
        case 'feature_engagement':
            return getFeatureEngagementRows(dateRange)
        case 'retention':
            return getRetentionRows(dateRange, compare)
    }
}
