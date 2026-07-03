import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { type CSSProperties, useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'
import { TrendInsight } from 'scenes/trends/Trends'

import { mswDecorator } from '~/mocks/browser'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import type { InsightLogicProps, InsightShortId } from '~/types'
import { InsightType } from '~/types'

import { TrendsBarChart } from './TrendsBarChart'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/TrendsBarChart',
    component: TrendsBarChart,
    parameters: {
        layout: 'centered',
        mockDate: '2023-07-11',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/annotations/': {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: 1,
                            content: 'Pricing page redesign shipped',
                            // Current-period marker. Pre-fix the badge sat between the
                            // bars at band center; post-fix it sits over the right
                            // (current-period) bar of band index 3 (Jul 7).
                            date_marker: '2023-07-07T12:00:00Z',
                            creation_type: 'USR',
                            dashboard_item: null,
                            created_by: {
                                id: 1,
                                uuid: '0188cbcf-2391-0000-1868-14fb987285c5',
                                distinct_id: 'storybook-user',
                                first_name: 'Story',
                                email: 'story@posthog.com',
                            },
                            created_at: '2023-07-07T12:00:00Z',
                            updated_at: '2023-07-07T12:00:00Z',
                            deleted: false,
                            scope: 'project',
                        },
                        {
                            id: 2,
                            content: 'Pricing page launched (previous period)',
                            // Previous-period marker, falls in the Jun 27 - Jul 3 window.
                            // Jul 1 → previous-period dataIndex 4 → left bar of band 4
                            // (under the "Jul 8" tick on the rendered axis).
                            date_marker: '2023-07-01T12:00:00Z',
                            creation_type: 'USR',
                            dashboard_item: null,
                            created_by: {
                                id: 1,
                                uuid: '0188cbcf-2391-0000-1868-14fb987285c5',
                                distinct_id: 'storybook-user',
                                first_name: 'Story',
                                email: 'story@posthog.com',
                            },
                            created_at: '2023-07-01T12:00:00Z',
                            updated_at: '2023-07-01T12:00:00Z',
                            deleted: false,
                            scope: 'project',
                        },
                    ],
                },
            },
        }),
    ],
}
export default meta

let uniqueNode = 0

function Stage({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ height: 360, width: 720, display: 'flex', flexDirection: 'column' }}>{children}</div>
    )
}

function renderTrendsBarChart(insightFixture: any): JSX.Element {
    const [dashboardItemId] = useState(() => `TrendsBarChartStory.${uniqueNode++}` as InsightShortId)
    const cachedInsight = { ...insightFixture, short_id: dashboardItemId }

    const insightProps: InsightLogicProps = { dashboardItemId, doNotLoad: true, cachedInsight }
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: cachedInsight.query.source,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(cachedInsight, cachedInsight.query.source),
        doNotLoad: true,
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <Stage>
                    <TrendsBarChart />
                </Stage>
            </BindLogic>
        </BindLogic>
    )
}

function renderTrendInsight(insightFixture: any): JSX.Element {
    const [dashboardItemId] = useState(() => `TrendsBarChartStory.${uniqueNode++}` as InsightShortId)
    const cachedInsight = { ...insightFixture, short_id: dashboardItemId }

    const insightProps: InsightLogicProps = { dashboardItemId, doNotLoad: true, cachedInsight }
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: cachedInsight.query.source,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(cachedInsight, cachedInsight.query.source),
        doNotLoad: true,
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                {/* TrendInsight renders `.TrendsInsight` but not the `.InsightVizDisplay` ancestor that
                    defines `--insight-viz-min-height`. Define it here so the chart's height behaves like the
                    real insight page — without it the standard-height floor no-ops and a single bar collapses. */}
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div style={{ width: 720, '--insight-viz-min-height': '32rem' } as CSSProperties}>
                    <TrendInsight view={InsightType.TRENDS} />
                </div>
            </BindLogic>
        </BindLogic>
    )
}

const CURRENT_DAYS = ['2023-07-04', '2023-07-05', '2023-07-06', '2023-07-07', '2023-07-08', '2023-07-09', '2023-07-10']
const CURRENT_LABELS = [
    '4-Jul-2023',
    '5-Jul-2023',
    '6-Jul-2023',
    '7-Jul-2023',
    '8-Jul-2023',
    '9-Jul-2023',
    '10-Jul-2023',
]
const PREVIOUS_DAYS = ['2023-06-27', '2023-06-28', '2023-06-29', '2023-06-30', '2023-07-01', '2023-07-02', '2023-07-03']
const PREVIOUS_LABELS = [
    '27-Jun-2023',
    '28-Jun-2023',
    '29-Jun-2023',
    '30-Jun-2023',
    '1-Jul-2023',
    '2-Jul-2023',
    '3-Jul-2023',
]

const ACTION = {
    id: '$pageview',
    type: 'events',
    order: 0,
    name: '$pageview',
    custom_name: null,
    math: 'total',
    math_property: null,
    math_hogql: null,
    math_group_type_index: null,
    properties: {},
}

// Compare-against-previous in unstacked-bar mode renders two bars per band (previous, current).
// Pre-fix, annotations anchored to the band center landed on the previous-period bar.
// The numbers below are intentionally distinct so the snapshot diffs the tall current bars
// from the shorter previous bars and the annotation sits over the current one.
const COMPARE_BAR_INSIGHT = {
    id: 200,
    short_id: 'barCompare',
    name: 'Pageviews compare',
    derived_name: 'Pageview count',
    filters: {},
    last_refresh: '2023-07-11T12:00:00Z',
    refreshing: false,
    saved: true,
    is_sample: false,
    description: '',
    tags: [],
    favorited: false,
    created_at: '2023-07-11T12:00:00Z',
    updated_at: '2023-07-11T12:00:00Z',
    last_modified_at: '2023-07-11T12:00:00Z',
    dashboards: [],
    dashboard_tiles: [],
    result: [
        {
            action: ACTION,
            label: '$pageview',
            count: 700,
            data: [120, 95, 110, 130, 140, 80, 125],
            labels: CURRENT_LABELS,
            days: CURRENT_DAYS,
            compare: true,
            compare_label: 'current',
            filter: {
                date_from: '2023-07-04T00:00:00Z',
                date_to: '2023-07-10T23:59:59Z',
                display: 'ActionsUnstackedBar',
                insight: 'TRENDS',
                interval: 'day',
            },
        },
        {
            action: ACTION,
            label: '$pageview',
            count: 420,
            data: [70, 60, 65, 75, 80, 50, 70],
            labels: PREVIOUS_LABELS,
            days: PREVIOUS_DAYS,
            compare: true,
            compare_label: 'previous',
            filter: {
                date_from: '2023-06-27T00:00:00Z',
                date_to: '2023-07-03T23:59:59Z',
                display: 'ActionsUnstackedBar',
                insight: 'TRENDS',
                interval: 'day',
            },
        },
    ],
    query: {
        kind: 'InsightVizNode',
        source: {
            dateRange: { date_from: '2023-07-04', date_to: '2023-07-10' },
            filterTestAccounts: false,
            interval: 'day',
            kind: 'TrendsQuery',
            series: [{ event: '$pageview', kind: 'EventsNode', math: 'total', name: '$pageview' }],
            trendsFilter: { display: 'ActionsUnstackedBar' },
            compareFilter: { compare: true },
            version: 2,
        },
        full: true,
    },
}

export const Compare: Story = {
    render: () => renderTrendsBarChart(COMPARE_BAR_INSIGHT),
}

const AGGREGATED_COMPARE_BREAKDOWN_INSIGHT = {
    id: 201,
    short_id: 'barValueCompare',
    name: 'Browser breakdown compare',
    derived_name: 'Pageview count',
    filters: {},
    last_refresh: '2023-07-11T12:00:00Z',
    refreshing: false,
    saved: true,
    is_sample: false,
    description: '',
    tags: [],
    favorited: false,
    created_at: '2023-07-11T12:00:00Z',
    updated_at: '2023-07-11T12:00:00Z',
    last_modified_at: '2023-07-11T12:00:00Z',
    dashboards: [],
    dashboard_tiles: [],
    result: [
        {
            action: ACTION,
            label: 'Chrome',
            count: 0,
            aggregated_value: 900,
            data: [],
            labels: [],
            days: [],
            breakdown_value: 'Chrome',
            compare: true,
            compare_label: 'current',
            filter: {
                date_from: '2023-07-04T00:00:00Z',
                date_to: '2023-07-10T23:59:59Z',
                display: 'ActionsBarValue',
                insight: 'TRENDS',
                interval: 'day',
            },
        },
        {
            action: ACTION,
            label: 'Chrome',
            count: 0,
            aggregated_value: 600,
            data: [],
            labels: [],
            days: [],
            breakdown_value: 'Chrome',
            compare: true,
            compare_label: 'previous',
            filter: {
                date_from: '2023-06-27T00:00:00Z',
                date_to: '2023-07-03T23:59:59Z',
                display: 'ActionsBarValue',
                insight: 'TRENDS',
                interval: 'day',
            },
        },
        {
            action: ACTION,
            label: 'Safari',
            count: 0,
            aggregated_value: 500,
            data: [],
            labels: [],
            days: [],
            breakdown_value: 'Safari',
            compare: true,
            compare_label: 'current',
            filter: {
                date_from: '2023-07-04T00:00:00Z',
                date_to: '2023-07-10T23:59:59Z',
                display: 'ActionsBarValue',
                insight: 'TRENDS',
                interval: 'day',
            },
        },
        {
            action: ACTION,
            label: 'Safari',
            count: 0,
            aggregated_value: 350,
            data: [],
            labels: [],
            days: [],
            breakdown_value: 'Safari',
            compare: true,
            compare_label: 'previous',
            filter: {
                date_from: '2023-06-27T00:00:00Z',
                date_to: '2023-07-03T23:59:59Z',
                display: 'ActionsBarValue',
                insight: 'TRENDS',
                interval: 'day',
            },
        },
    ],
    query: {
        kind: 'InsightVizNode',
        source: {
            dateRange: { date_from: '2023-07-04', date_to: '2023-07-10' },
            filterTestAccounts: false,
            interval: 'day',
            kind: 'TrendsQuery',
            series: [{ event: '$pageview', kind: 'EventsNode', math: 'total', name: '$pageview' }],
            trendsFilter: { display: 'ActionsBarValue' },
            breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
            compareFilter: { compare: true },
            version: 2,
        },
        full: true,
    },
}

export const AggregatedCompareBreakdown: Story = {
    render: () => renderTrendsBarChart(AGGREGATED_COMPARE_BREAKDOWN_INSIGHT),
}

// Stacked bar in 100% mode with value labels enabled. Pre-fix this snapshot showed a 0%–1%
// y-axis, raw-count value labels (e.g. "22,865%"), and a clipped top-segment label. After
// the fix the y-axis runs 0%–100%, labels show each segment's share, and the topmost label
// sits inside its segment.
const PERCENT_STACK_BREAKDOWN_INSIGHT = {
    id: 202,
    short_id: 'barPercentStack',
    name: 'Pageviews by browser (100% stacked)',
    derived_name: 'Pageview count',
    filters: {},
    last_refresh: '2023-07-11T12:00:00Z',
    refreshing: false,
    saved: true,
    is_sample: false,
    description: '',
    tags: [],
    favorited: false,
    created_at: '2023-07-11T12:00:00Z',
    updated_at: '2023-07-11T12:00:00Z',
    last_modified_at: '2023-07-11T12:00:00Z',
    dashboards: [],
    dashboard_tiles: [],
    result: [
        {
            action: ACTION,
            label: 'Chrome',
            count: 14000,
            data: [4000, 3500, 3000, 1500, 1200, 600, 200],
            labels: CURRENT_LABELS,
            days: CURRENT_DAYS,
            breakdown_value: 'Chrome',
            filter: {
                date_from: '2023-07-04T00:00:00Z',
                date_to: '2023-07-10T23:59:59Z',
                display: 'ActionsBar',
                insight: 'TRENDS',
                interval: 'day',
            },
        },
        {
            action: ACTION,
            label: 'Safari',
            count: 6500,
            data: [400, 800, 1500, 1800, 1500, 400, 100],
            labels: CURRENT_LABELS,
            days: CURRENT_DAYS,
            breakdown_value: 'Safari',
            filter: {
                date_from: '2023-07-04T00:00:00Z',
                date_to: '2023-07-10T23:59:59Z',
                display: 'ActionsBar',
                insight: 'TRENDS',
                interval: 'day',
            },
        },
        {
            action: ACTION,
            label: 'Firefox',
            count: 2200,
            data: [200, 250, 300, 500, 500, 350, 100],
            labels: CURRENT_LABELS,
            days: CURRENT_DAYS,
            breakdown_value: 'Firefox',
            filter: {
                date_from: '2023-07-04T00:00:00Z',
                date_to: '2023-07-10T23:59:59Z',
                display: 'ActionsBar',
                insight: 'TRENDS',
                interval: 'day',
            },
        },
        {
            action: ACTION,
            label: 'Edge',
            count: 900,
            data: [80, 120, 150, 200, 200, 100, 50],
            labels: CURRENT_LABELS,
            days: CURRENT_DAYS,
            breakdown_value: 'Edge',
            filter: {
                date_from: '2023-07-04T00:00:00Z',
                date_to: '2023-07-10T23:59:59Z',
                display: 'ActionsBar',
                insight: 'TRENDS',
                interval: 'day',
            },
        },
    ],
    query: {
        kind: 'InsightVizNode',
        source: {
            dateRange: { date_from: '2023-07-04', date_to: '2023-07-10' },
            filterTestAccounts: false,
            interval: 'day',
            kind: 'TrendsQuery',
            series: [{ event: '$pageview', kind: 'EventsNode', math: 'total', name: '$pageview' }],
            trendsFilter: {
                display: 'ActionsBar',
                showPercentStackView: true,
                showValuesOnSeries: true,
            },
            breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
            version: 2,
        },
        full: true,
    },
}

export const PercentStackBreakdown: Story = {
    render: () => renderTrendsBarChart(PERCENT_STACK_BREAKDOWN_INSIGHT),
}

// 50 breakdown rows — verifies all bars are visible and the container grows rather than clipping.
// If TrendsInsight--ActionsBarValue loses its max-height:none override, only ~20 rows show up.
const BAR_VALUE_50_BREAKDOWNS = Array.from({ length: 50 }, (_, i) => ({
    action: ACTION,
    label: `/blog/post-${String(i + 1).padStart(2, '0')}`,
    count: 0,
    aggregated_value: Math.max(5, Math.round(9000 / (i + 1))),
    data: [],
    labels: [],
    days: [],
    breakdown_value: `/blog/post-${String(i + 1).padStart(2, '0')}`,
    filter: {
        date_from: '2023-07-04T00:00:00Z',
        date_to: '2023-07-10T23:59:59Z',
        display: 'ActionsBarValue',
        insight: 'TRENDS',
        interval: 'day',
    },
}))

const BAR_VALUE_50_BREAKDOWNS_INSIGHT = {
    id: 203,
    short_id: 'barValue50',
    name: 'Page views by URL (50 breakdowns)',
    derived_name: 'Pageview count',
    filters: {},
    last_refresh: '2023-07-11T12:00:00Z',
    refreshing: false,
    saved: true,
    is_sample: false,
    description: '',
    tags: [],
    favorited: false,
    created_at: '2023-07-11T12:00:00Z',
    updated_at: '2023-07-11T12:00:00Z',
    last_modified_at: '2023-07-11T12:00:00Z',
    dashboards: [],
    dashboard_tiles: [],
    result: BAR_VALUE_50_BREAKDOWNS,
    query: {
        kind: 'InsightVizNode',
        source: {
            dateRange: { date_from: '2023-07-04', date_to: '2023-07-10' },
            filterTestAccounts: false,
            interval: 'day',
            kind: 'TrendsQuery',
            series: [{ event: '$pageview', kind: 'EventsNode', math: 'total', name: '$pageview' }],
            trendsFilter: { display: 'ActionsBarValue' },
            breakdownFilter: { breakdown: '$current_url', breakdown_type: 'event' },
            version: 2,
        },
        full: true,
    },
}

export const BarValue50Breakdowns: Story = {
    render: () => renderTrendInsight(BAR_VALUE_50_BREAKDOWNS_INSIGHT),
}

// A single breakdown row should still fill the standard chart height — the lone bar must not
// shrink. Guards the min-height floor on TrendsInsight--ActionsBarValue: drop it back to `auto`
// and this snapshot collapses to a thin one-row bar instead of filling the container.
const BAR_VALUE_SINGLE_BREAKDOWN_INSIGHT = {
    ...BAR_VALUE_50_BREAKDOWNS_INSIGHT,
    id: 204,
    short_id: 'barValueSingle',
    name: 'Page views by URL (single breakdown)',
    result: BAR_VALUE_50_BREAKDOWNS.slice(0, 1),
}

export const BarValueSingleBreakdown: Story = {
    render: () => renderTrendInsight(BAR_VALUE_SINGLE_BREAKDOWN_INSIGHT),
}
