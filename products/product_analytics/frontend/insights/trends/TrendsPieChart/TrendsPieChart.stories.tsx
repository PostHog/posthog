import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { mswDecorator } from '~/mocks/browser'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import type { InsightLogicProps, InsightShortId } from '~/types'

import { TrendsPieChart } from './TrendsPieChart'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/TrendsPieChart',
    component: TrendsPieChart,
    parameters: {
        layout: 'centered',
        mockDate: '2023-07-11',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/annotations/': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
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

function renderTrendsPieChart(insightFixture: any): JSX.Element {
    const [dashboardItemId] = useState(() => `TrendsPieChartStory.${uniqueNode++}` as InsightShortId)
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
                    <TrendsPieChart />
                </Stage>
            </BindLogic>
        </BindLogic>
    )
}

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

const PIE_SINGLE_INSIGHT = {
    id: 300,
    short_id: 'pieSingle',
    name: 'Pageviews pie',
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
            count: 0,
            data: [],
            labels: [],
            days: ['2023-07-04', '2023-07-05', '2023-07-06', '2023-07-07', '2023-07-08', '2023-07-09', '2023-07-10'],
            aggregated_value: 47258,
            filter: {
                date_from: '2023-07-04T00:00:00Z',
                date_to: '2023-07-10T23:59:59Z',
                display: 'ActionsPie',
                insight: 'TRENDS',
                interval: 'day',
            },
        },
        {
            action: ACTION,
            label: '$pageleave',
            count: 0,
            data: [],
            labels: [],
            days: ['2023-07-04', '2023-07-05', '2023-07-06', '2023-07-07', '2023-07-08', '2023-07-09', '2023-07-10'],
            aggregated_value: 3258,
            filter: {
                date_from: '2023-07-04T00:00:00Z',
                date_to: '2023-07-10T23:59:59Z',
                display: 'ActionsPie',
                insight: 'TRENDS',
                interval: 'day',
            },
        },
    ],
    query: {
        kind: 'InsightVizNode',
        source: {
            filterTestAccounts: false,
            interval: 'day',
            kind: 'TrendsQuery',
            series: [
                { event: '$pageview', kind: 'EventsNode', math: 'total', name: '$pageview' },
                { event: '$pageleave', kind: 'EventsNode', math: 'total', name: '$pageleave' },
            ],
            trendsFilter: { display: 'ActionsPie' },
            version: 2,
        },
        full: true,
    },
}

export const Default: Story = {
    render: () => renderTrendsPieChart(PIE_SINGLE_INSIGHT),
}

const PIE_BREAKDOWN_INSIGHT = {
    id: 301,
    short_id: 'pieBreakdown',
    name: 'Browser breakdown pie',
    derived_name: 'Pageview count by Browser Version',
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
            label: '$pageview - Chrome',
            count: 0,
            data: [],
            labels: [],
            days: ['2023-07-04', '2023-07-05', '2023-07-06', '2023-07-07', '2023-07-08', '2023-07-09', '2023-07-10'],
            aggregated_value: 44182,
            breakdown_value: 'Chrome',
            filter: {
                breakdown: '$browser',
                breakdown_type: 'event',
                date_from: '2023-07-04T00:00:00Z',
                date_to: '2023-07-10T23:59:59Z',
                display: 'ActionsPie',
                insight: 'TRENDS',
                interval: 'day',
            },
        },
        {
            action: ACTION,
            label: '$pageview - Safari',
            count: 0,
            data: [],
            labels: [],
            days: ['2023-07-04', '2023-07-05', '2023-07-06', '2023-07-07', '2023-07-08', '2023-07-09', '2023-07-10'],
            aggregated_value: 2478,
            breakdown_value: 'Safari',
            filter: {
                breakdown: '$browser',
                breakdown_type: 'event',
                date_from: '2023-07-04T00:00:00Z',
                date_to: '2023-07-10T23:59:59Z',
                display: 'ActionsPie',
                insight: 'TRENDS',
                interval: 'day',
            },
        },
        {
            action: ACTION,
            label: '$pageview - Firefox',
            count: 0,
            data: [],
            labels: [],
            days: ['2023-07-04', '2023-07-05', '2023-07-06', '2023-07-07', '2023-07-08', '2023-07-09', '2023-07-10'],
            aggregated_value: 598,
            breakdown_value: 'Firefox',
            filter: {
                breakdown: '$browser',
                breakdown_type: 'event',
                date_from: '2023-07-04T00:00:00Z',
                date_to: '2023-07-10T23:59:59Z',
                display: 'ActionsPie',
                insight: 'TRENDS',
                interval: 'day',
            },
        },
    ],
    query: {
        kind: 'InsightVizNode',
        source: {
            breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
            filterTestAccounts: false,
            interval: 'day',
            kind: 'TrendsQuery',
            series: [{ event: '$pageview', kind: 'EventsNode', math: 'total', name: '$pageview' }],
            trendsFilter: { display: 'ActionsPie' },
            version: 2,
        },
        full: true,
    },
}

export const Breakdown: Story = {
    render: () => renderTrendsPieChart(PIE_BREAKDOWN_INSIGHT),
}

const PIE_LABELS_INSIGHT = {
    ...PIE_BREAKDOWN_INSIGHT,
    id: 302,
    short_id: 'pieLabels',
    name: 'Pie with labels on series',
    query: {
        kind: 'InsightVizNode',
        source: {
            ...PIE_BREAKDOWN_INSIGHT.query.source,
            trendsFilter: { display: 'ActionsPie', showLabelOnSeries: true, showValuesOnSeries: true },
        },
        full: true,
    },
}

export const BreakdownWithLabels: Story = {
    render: () => renderTrendsPieChart(PIE_LABELS_INSIGHT),
}
