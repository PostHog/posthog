import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { dataNodeLogic } from '@posthog/query-frontend/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '@posthog/query-frontend/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '@posthog/query-frontend/nodes/InsightViz/InsightViz'
import { getCachedResults } from '@posthog/query-frontend/nodes/InsightViz/utils'

import { insightLogic } from 'scenes/insights/insightLogic'

import { mswDecorator } from '~/mocks/browser'
import stickinessFixture from '~/mocks/fixtures/api/projects/team_id/insights/stickiness.json'
import { ChartDisplayType, InsightLogicProps, InsightShortId } from '~/types'

import { StickinessLineChart } from './StickinessLineChart'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/StickinessLineChart',
    component: StickinessLineChart,
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

function StickinessLineChartStory({ insightFixture }: { insightFixture: any }): JSX.Element {
    const [dashboardItemId] = useState(() => `StickinessLineChartStory.${uniqueNode++}` as InsightShortId)
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
                    <StickinessLineChart />
                </Stage>
            </BindLogic>
        </BindLogic>
    )
}

export const Default: Story = {
    render: () => <StickinessLineChartStory insightFixture={stickinessFixture} />,
}

const areaFixture = {
    ...stickinessFixture,
    query: {
        ...stickinessFixture.query,
        source: {
            ...stickinessFixture.query.source,
            stickinessFilter: { display: ChartDisplayType.ActionsAreaGraph },
        },
    },
}

export const Area: Story = {
    render: () => <StickinessLineChartStory insightFixture={areaFixture} />,
}
