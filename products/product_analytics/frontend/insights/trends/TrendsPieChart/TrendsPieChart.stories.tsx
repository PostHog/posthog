import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

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
}
export default meta

let uniqueNode = 0

function Stage({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ height: 360, width: 480, display: 'flex', flexDirection: 'column' }}>{children}</div>
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

function breakdownSlice(label: string, aggregated_value: number): Record<string, any> {
    return {
        action: ACTION,
        label,
        count: 0,
        aggregated_value,
        data: [],
        labels: [],
        days: [],
        breakdown_value: label,
        filter: {
            date_from: '2023-07-04T00:00:00Z',
            date_to: '2023-07-10T23:59:59Z',
            display: 'ActionsPie',
            insight: 'TRENDS',
            interval: 'day',
        },
    }
}

function pieInsight(trendsFilter: Record<string, any>, shortId: string): Record<string, any> {
    return {
        id: 300,
        short_id: shortId,
        name: 'Pageviews by browser',
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
            breakdownSlice('Chrome', 900),
            breakdownSlice('Safari', 500),
            breakdownSlice('Firefox', 220),
            breakdownSlice('Edge', 90),
        ],
        query: {
            kind: 'InsightVizNode',
            source: {
                dateRange: { date_from: '2023-07-04', date_to: '2023-07-10' },
                filterTestAccounts: false,
                interval: 'day',
                kind: 'TrendsQuery',
                series: [{ event: '$pageview', kind: 'EventsNode', math: 'total', name: '$pageview' }],
                trendsFilter,
                breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
                version: 2,
            },
            full: true,
        },
    }
}

export const Breakdown: Story = {
    render: () => renderTrendsPieChart(pieInsight({ display: 'ActionsPie', showValuesOnSeries: true }, 'pieBreakdown')),
}

// With "Show as % of total" enabled, slice labels render each slice's share of the total
// (e.g. "52.3%") rather than its raw count.
export const PercentStackBreakdown: Story = {
    render: () =>
        renderTrendsPieChart(
            pieInsight(
                { display: 'ActionsPie', showValuesOnSeries: true, showPercentStackView: true },
                'piePercentStack'
            )
        ),
}
