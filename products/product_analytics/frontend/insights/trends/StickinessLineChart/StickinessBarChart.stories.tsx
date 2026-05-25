import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { mswDecorator } from '~/mocks/browser'
import stickinessFixture from '~/mocks/fixtures/api/projects/team_id/insights/stickiness.json'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import { ChartDisplayType, InsightLogicProps, InsightShortId } from '~/types'

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

function buildFixture(display: ChartDisplayType): any {
    const base = stickinessFixture as any
    return {
        ...base,
        query: {
            ...base.query,
            source: {
                ...base.query.source,
                stickinessFilter: { display },
            },
        },
    }
}

function StickinessBarChartStory({ fixture }: { fixture: any }): JSX.Element {
    const [dashboardItemId] = useState(() => `StickinessBarChartStory.${uniqueNode++}` as InsightShortId)
    const cachedInsight = { ...fixture, short_id: dashboardItemId }

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

export const Stacked: Story = {
    render: () => <StickinessBarChartStory fixture={buildFixture(ChartDisplayType.ActionsBar)} />,
}

export const Unstacked: Story = {
    render: () => <StickinessBarChartStory fixture={buildFixture(ChartDisplayType.ActionsUnstackedBar)} />,
}
