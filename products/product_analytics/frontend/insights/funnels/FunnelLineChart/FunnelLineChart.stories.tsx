import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { mswDecorator } from '~/mocks/browser'
import funnelHistoricalTrendsFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelHistoricalTrends.json'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import type { FunnelsFilter } from '~/queries/schema/schema-general'
import { InsightLogicProps, InsightShortId } from '~/types'

import { FunnelLineChart } from './FunnelLineChart'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/FunnelLineChart',
    component: FunnelLineChart,
    parameters: {
        layout: 'centered',
        mockDate: '2022-03-12',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/annotations/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: 1,
                            content: 'Funnel optimization shipped',
                            date_marker: '2022-03-10T12:00:00Z',
                            creation_type: 'USR',
                            dashboard_item: null,
                            created_by: {
                                id: 1,
                                uuid: '0188cbcf-2391-0000-1868-14fb987285c5',
                                distinct_id: 'storybook-user',
                                first_name: 'Story',
                                email: 'story@posthog.com',
                            },
                            created_at: '2022-03-10T12:00:00Z',
                            updated_at: '2022-03-10T12:00:00Z',
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

function renderFunnelLineChart(insightFixture: any, funnelsFilterOverrides?: Partial<FunnelsFilter>): JSX.Element {
    const [dashboardItemId] = useState(() => `FunnelLineChartStory.${uniqueNode++}` as InsightShortId)
    const source = {
        ...insightFixture.query.source,
        funnelsFilter: { ...insightFixture.query.source.funnelsFilter, ...funnelsFilterOverrides },
    }
    const cachedInsight = { ...insightFixture, short_id: dashboardItemId, query: { ...insightFixture.query, source } }

    const insightProps: InsightLogicProps = { dashboardItemId, doNotLoad: true, cachedInsight }
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: source,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(cachedInsight, source),
        doNotLoad: true,
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <Stage>
                    <FunnelLineChart />
                </Stage>
            </BindLogic>
        </BindLogic>
    )
}

export const Default: Story = {
    render: () => renderFunnelLineChart(funnelHistoricalTrendsFixture),
}

export const ValueLabels: Story = {
    render: () => renderFunnelLineChart(funnelHistoricalTrendsFixture, { showValuesOnSeries: true }),
}

export const GoalLine: Story = {
    render: () =>
        renderFunnelLineChart(funnelHistoricalTrendsFixture, {
            goalLines: [{ label: 'Target', value: 10, displayIfCrossed: true }],
        }),
}
