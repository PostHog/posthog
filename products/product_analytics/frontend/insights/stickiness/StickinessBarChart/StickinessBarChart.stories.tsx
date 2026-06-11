import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { mswDecorator } from '~/mocks/browser'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import { type InsightLogicProps, type InsightShortId } from '~/types'

import { StickinessBarChart } from './StickinessBarChart'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/StickinessBarChart',
    component: StickinessBarChart,
    parameters: {
        layout: 'centered',
        mockDate: '2022-03-15',
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

function StickinessBarChartStory({ insightFixture }: { insightFixture: any }): JSX.Element {
    const [dashboardItemId] = useState(() => `StickinessBarChartStory.${uniqueNode++}` as InsightShortId)
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
                    <StickinessBarChart />
                </Stage>
            </BindLogic>
        </BindLogic>
    )
}

const STICKINESS_DAYS = [1, 2, 3, 4, 5, 6, 7, 8]
const STICKINESS_LABELS = STICKINESS_DAYS.map((d) => (d === 1 ? '1 day' : `${d} days`))

const ACTION = {
    id: '$pageview',
    type: 'events',
    order: 0,
    name: '$pageview',
    custom_name: null,
    math: null,
    math_property: null,
    math_group_type_index: null,
    properties: {},
}

function buildStickinessInsight({
    display,
    id,
    short_id,
    results,
}: {
    display: 'ActionsBar' | 'ActionsUnstackedBar'
    id: number
    short_id: string
    results: Array<{
        label: string
        count: number
        data: number[]
        breakdown_value?: string
    }>
}): Record<string, unknown> {
    return {
        id,
        short_id,
        name: 'Pageview stickiness',
        derived_name: 'User stickiness based on Pageview',
        filters: {},
        last_refresh: '2022-03-15T21:50:39Z',
        refreshing: false,
        saved: true,
        is_sample: false,
        description: '',
        tags: [],
        favorited: false,
        created_at: '2022-03-15T21:31:00Z',
        updated_at: '2022-03-15T21:50:39Z',
        last_modified_at: '2022-03-15T21:50:39Z',
        dashboards: [],
        dashboard_tiles: [],
        result: results.map((r) => ({
            action: ACTION,
            label: r.label,
            count: r.count,
            data: r.data,
            labels: STICKINESS_LABELS,
            days: STICKINESS_DAYS,
            breakdown_value: r.breakdown_value,
            filter: {
                date_from: '2022-03-08T00:00:00Z',
                insight: 'STICKINESS',
                interval: 'day',
                shown_as: 'Stickiness',
            },
        })),
        query: {
            kind: 'InsightVizNode',
            source: {
                kind: 'StickinessQuery',
                interval: 'day',
                series: [{ event: '$pageview', kind: 'EventsNode', name: '$pageview' }],
                stickinessFilter: { display },
                version: 2,
            },
            full: true,
        },
    }
}

const BROWSER_BREAKDOWN_RESULTS = [
    { label: 'Chrome', count: 12000, data: [9500, 1800, 400, 200, 80, 10, 8, 2], breakdown_value: 'Chrome' },
    { label: 'Safari', count: 6000, data: [4800, 900, 200, 60, 30, 5, 3, 2], breakdown_value: 'Safari' },
    { label: 'Firefox', count: 2400, data: [1900, 350, 100, 30, 12, 5, 2, 1], breakdown_value: 'Firefox' },
]

const STACKED_INSIGHT = buildStickinessInsight({
    display: 'ActionsBar',
    id: 301,
    short_id: 'stickyBarStacked',
    results: BROWSER_BREAKDOWN_RESULTS,
})

export const Stacked: Story = {
    render: () => <StickinessBarChartStory insightFixture={STACKED_INSIGHT} />,
}

const UNSTACKED_INSIGHT = buildStickinessInsight({
    display: 'ActionsUnstackedBar',
    id: 302,
    short_id: 'stickyBarGrouped',
    results: BROWSER_BREAKDOWN_RESULTS,
})

export const Unstacked: Story = {
    render: () => <StickinessBarChartStory insightFixture={UNSTACKED_INSIGHT} />,
}
