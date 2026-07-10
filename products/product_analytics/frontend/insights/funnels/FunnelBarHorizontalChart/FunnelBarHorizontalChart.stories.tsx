import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import funnelTopToBottomFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'
import funnelTopToBottomBreakdownFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomBreakdown.json'
import funnelTopToBottomBreakdownCompareFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomBreakdownCompare.json'
import funnelTopToBottomCompareFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomCompare.json'
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

// Compare to previous: each step renders two stacked bars (current solid above, previous desaturated
// below), each scaled to the shared baseline — not two periods crammed into one bar.
export const FunnelTopToBottomCompare: Story = {
    render: () => <StoryRender insightFixture={funnelTopToBottomCompareFixture} width={720} />,
}

// Breakdown + compare: each step stacks a bar per (breakdown value, period), paired by value with
// the previous-period bar desaturated under its current-period sibling.
export const FunnelTopToBottomBreakdownCompare: Story = {
    render: () => <StoryRender insightFixture={funnelTopToBottomBreakdownCompareFixture} width={720} />,
}

// Narrow widths force the step footers to wrap — each row should grow to fit its own text
// without overlapping the next step.
export const DefaultNarrow: Story = {
    render: () => <StoryRender insightFixture={funnelTopToBottomFixture} width={320} />,
}

export const BreakdownNarrow: Story = {
    render: () => <StoryRender insightFixture={funnelTopToBottomBreakdownFixture} width={320} />,
}
