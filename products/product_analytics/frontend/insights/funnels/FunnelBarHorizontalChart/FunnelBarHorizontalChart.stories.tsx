import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import funnelTopToBottomFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'
import funnelTopToBottomBreakdownFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomBreakdown.json'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import { InsightLogicProps, InsightShortId } from '~/types'

import { FunnelBarHorizontalChart } from './FunnelBarHorizontalChart'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/FunnelBarHorizontalChart',
    component: FunnelBarHorizontalChart,
    parameters: {
        layout: 'centered',
        mockDate: '2022-03-12',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

let uniqueNode = 0

function Stage({ children, width }: { children: React.ReactNode; width: number }): JSX.Element {
    // eslint-disable-next-line react/forbid-dom-props
    return <div style={{ width }}>{children}</div>
}

function StoryRender({ insightFixture, width }: { insightFixture: any; width: number }): JSX.Element {
    const [dashboardItemId] = useState(() => `FunnelBarHorizontalChartStory.${uniqueNode++}` as InsightShortId)
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
                <Stage width={width}>
                    <FunnelBarHorizontalChart />
                </Stage>
            </BindLogic>
        </BindLogic>
    )
}

export const Default: Story = {
    render: () => <StoryRender insightFixture={funnelTopToBottomFixture} width={720} />,
}

export const Breakdown: Story = {
    render: () => <StoryRender insightFixture={funnelTopToBottomBreakdownFixture} width={720} />,
}

// A narrow width forces footers to wrap — each row should grow to fit its text, not overlap the next.
export const DefaultNarrow: Story = {
    render: () => <StoryRender insightFixture={funnelTopToBottomFixture} width={320} />,
}
