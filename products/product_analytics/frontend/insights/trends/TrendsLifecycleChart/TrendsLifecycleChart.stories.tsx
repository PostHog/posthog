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

import { TrendsLifecycleChart } from './TrendsLifecycleChart'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/TrendsLifecycleChart',
    component: TrendsLifecycleChart,
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

function LifecycleStory({ insightFixture }: { insightFixture: any }): JSX.Element {
    const [dashboardItemId] = useState(() => `TrendsLifecycleChartStory.${uniqueNode++}` as InsightShortId)
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
                    <TrendsLifecycleChart />
                </Stage>
            </BindLogic>
        </BindLogic>
    )
}

const LIFECYCLE_DAYS = [
    '2023-07-04',
    '2023-07-05',
    '2023-07-06',
    '2023-07-07',
    '2023-07-08',
    '2023-07-09',
    '2023-07-10',
]
const LIFECYCLE_LABELS = [
    '4-Jul-2023',
    '5-Jul-2023',
    '6-Jul-2023',
    '7-Jul-2023',
    '8-Jul-2023',
    '9-Jul-2023',
    '10-Jul-2023',
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

const lifecycleSeries = (status: 'new' | 'returning' | 'resurrecting' | 'dormant', data: number[]): object => ({
    action: ACTION,
    label: `$pageview - ${status}`,
    count: data.reduce((a, b) => a + b, 0),
    aggregated_value: data.reduce((a, b) => a + b, 0),
    data,
    labels: LIFECYCLE_LABELS,
    days: LIFECYCLE_DAYS,
    status,
})

interface LifecycleInsightOpts {
    stacked: boolean
    id: number
    shortId: string
    name?: string
    showValuesOnSeries?: boolean
    showPercentagesOnSeries?: boolean
    showLegend?: boolean
}

function lifecycleInsight({
    stacked,
    id,
    shortId,
    name,
    showValuesOnSeries,
    showPercentagesOnSeries,
    showLegend,
}: LifecycleInsightOpts): object {
    return {
        id,
        short_id: shortId,
        name: name ?? (stacked ? 'Lifecycle stacked' : 'Lifecycle unstacked'),
        derived_name: 'Lifecycle',
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
        // The order intentionally does NOT match the chart's rendered dormant → returning →
        // resurrecting → new order — the transform sorts by status, so the chart should look
        // the same regardless of how the API returns the rows.
        result: [
            lifecycleSeries('returning', [42, 38, 45, 40, 50, 47, 44]),
            lifecycleSeries('new', [22, 30, 18, 24, 28, 20, 26]),
            lifecycleSeries('dormant', [-12, -10, -8, -14, -10, -9, -11]),
            lifecycleSeries('resurrecting', [6, 8, 5, 9, 7, 6, 8]),
        ],
        query: {
            kind: 'InsightVizNode',
            source: {
                dateRange: { date_from: '2023-07-04', date_to: '2023-07-10' },
                filterTestAccounts: false,
                interval: 'day',
                kind: 'LifecycleQuery',
                series: [{ event: '$pageview', kind: 'EventsNode', math: 'total', name: '$pageview' }],
                lifecycleFilter: { stacked, showValuesOnSeries, showPercentagesOnSeries, showLegend },
                version: 2,
            },
            full: true,
        },
    }
}

export const Stacked: Story = {
    render: () => (
        <LifecycleStory insightFixture={lifecycleInsight({ stacked: true, id: 300, shortId: 'lifecycleStacked' })} />
    ),
}

export const Unstacked: Story = {
    render: () => (
        <LifecycleStory insightFixture={lifecycleInsight({ stacked: false, id: 301, shortId: 'lifecycleUnstacked' })} />
    ),
}

export const StackedWithValuesOnSeries: Story = {
    render: () => (
        <LifecycleStory
            insightFixture={lifecycleInsight({
                stacked: true,
                id: 302,
                shortId: 'lifecycleStackedValues',
                name: 'Lifecycle stacked (values on series)',
                showValuesOnSeries: true,
            })}
        />
    ),
}

export const UnstackedWithValuesOnSeries: Story = {
    render: () => (
        <LifecycleStory
            insightFixture={lifecycleInsight({
                stacked: false,
                id: 303,
                shortId: 'lifecycleUnstackedValues',
                name: 'Lifecycle unstacked (values on series)',
                showValuesOnSeries: true,
            })}
        />
    ),
}

export const StackedWithPercentagesOnSeries: Story = {
    render: () => (
        <LifecycleStory
            insightFixture={lifecycleInsight({
                stacked: true,
                id: 304,
                shortId: 'lifecycleStackedPercentages',
                name: 'Lifecycle stacked (values + percentages on series)',
                showValuesOnSeries: true,
                showPercentagesOnSeries: true,
            })}
        />
    ),
}

export const UnstackedWithPercentagesOnSeries: Story = {
    render: () => (
        <LifecycleStory
            insightFixture={lifecycleInsight({
                stacked: false,
                id: 305,
                shortId: 'lifecycleUnstackedPercentages',
                name: 'Lifecycle unstacked (values + percentages on series)',
                showValuesOnSeries: true,
                showPercentagesOnSeries: true,
            })}
        />
    ),
}

export const StackedWithPercentagesOnlyOnSeries: Story = {
    render: () => (
        <LifecycleStory
            insightFixture={lifecycleInsight({
                stacked: true,
                id: 306,
                shortId: 'lifecycleStackedPercentagesOnly',
                name: 'Lifecycle stacked (percentages only on series)',
                showValuesOnSeries: false,
                showPercentagesOnSeries: true,
            })}
        />
    ),
}

export const StackedWithLegend: Story = {
    render: () => (
        <LifecycleStory
            insightFixture={lifecycleInsight({
                stacked: true,
                id: 307,
                shortId: 'lifecycleStackedLegend',
                name: 'Lifecycle stacked (with legend)',
                showLegend: true,
            })}
        />
    ),
}

export const UnstackedWithLegend: Story = {
    render: () => (
        <LifecycleStory
            insightFixture={lifecycleInsight({
                stacked: false,
                id: 308,
                shortId: 'lifecycleUnstackedLegend',
                name: 'Lifecycle unstacked (with legend)',
                showLegend: true,
            })}
        />
    ),
}
