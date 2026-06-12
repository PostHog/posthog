import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { dataNodeLogic } from '@posthog/query-frontend/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '@posthog/query-frontend/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '@posthog/query-frontend/nodes/InsightViz/InsightViz'
import { getCachedResults } from '@posthog/query-frontend/nodes/InsightViz/utils'

import { insightLogic } from 'scenes/insights/insightLogic'

import funnelTopToBottomFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'
import funnelTopToBottomBreakdownFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomBreakdown.json'
import { InsightLogicProps, InsightShortId } from '~/types'

import { FunnelStepsBarChart } from './FunnelStepsBarChart'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/FunnelStepsBarChart',
    component: FunnelStepsBarChart,
    parameters: {
        layout: 'centered',
        mockDate: '2022-03-12',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

let uniqueNode = 0

function Stage({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ height: 420, width: 720, display: 'flex', flexDirection: 'column' }}>{children}</div>
    )
}

function StoryRender({ insightFixture }: { insightFixture: any }): JSX.Element {
    const [dashboardItemId] = useState(() => `FunnelStepsBarChartStory.${uniqueNode++}` as InsightShortId)
    const source = insightFixture.query.source
    const cachedInsight = { ...insightFixture, short_id: dashboardItemId }

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
                    <FunnelStepsBarChart />
                </Stage>
            </BindLogic>
        </BindLogic>
    )
}

export const Default: Story = {
    render: () => <StoryRender insightFixture={funnelTopToBottomFixture} />,
}

export const Breakdown: Story = {
    render: () => <StoryRender insightFixture={funnelTopToBottomBreakdownFixture} />,
}
