import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import {
    createInsightStory,
    expandFirstPropertyFilter,
    insightSceneMswDecorator,
    insightSceneStoryParameters,
    waitForFunnelToStabilize,
} from 'scenes/insights/__mocks__/createInsightScene'
import { insightLogic } from 'scenes/insights/insightLogic'

import funnelLeftToRightFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'
import funnelLeftToRightWithInlineEventsFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelLeftToRightWithInlineEvents.json'
import funnelTopToBottomFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'
import funnelTopToBottomBreakdownFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomBreakdown.json'
import funnelTopToBottomBreakdownCompareFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomBreakdownCompare.json'
import funnelTopToBottomCompareFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomCompare.json'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
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

// Compare to previous: each step shows the periods as side-by-side columns (previous left of current),
// each capped at its period's entry level so a shorter period leaves a blank volume gap above its track.
export const Compare: Story = {
    render: () => <StoryRender insightFixture={funnelTopToBottomCompareFixture} />,
    parameters: { featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_FUNNELS_COMPARE] },
}

// Breakdown + compare: each breakdown value shows its own conversion within its period, and the two
// periods are scaled against each other — at the first step every value shares its period's height, the
// larger period filling the column and the smaller one proportionally short, leaving a blank gap above.
export const BreakdownAndCompare: Story = {
    render: () => <StoryRender insightFixture={funnelTopToBottomBreakdownCompareFixture} />,
    parameters: { featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_FUNNELS_COMPARE] },
}

// Full insight scene in edit mode — the steps funnel editor, and the funnels query kind's full data pipeline
const sceneEditWaitForSelector = ['[data-attr=funnel-steps-bar-chart] canvas[role="img"]', '.PayGateMini']

export const EditScene: Story = createInsightStory(funnelLeftToRightFixture as any, 'edit')
EditScene.decorators = [insightSceneMswDecorator]
EditScene.parameters = {
    ...insightSceneStoryParameters,
    testOptions: { ...insightSceneStoryParameters.testOptions, waitForSelector: sceneEditWaitForSelector },
}

export const EditSceneWithInlineEvents: Story = createInsightStory(
    funnelLeftToRightWithInlineEventsFixture as any,
    'edit'
)
EditSceneWithInlineEvents.decorators = [insightSceneMswDecorator]
EditSceneWithInlineEvents.parameters = {
    ...insightSceneStoryParameters,
    testOptions: { ...insightSceneStoryParameters.testOptions, waitForSelector: sceneEditWaitForSelector },
}
EditSceneWithInlineEvents.play = expandFirstPropertyFilter

export const EditSceneViewports: Story = createInsightStory(funnelLeftToRightFixture as any, 'edit')
EditSceneViewports.decorators = [insightSceneMswDecorator]
EditSceneViewports.parameters = {
    ...insightSceneStoryParameters,
    testOptions: {
        ...insightSceneStoryParameters.testOptions,
        waitForSelector: sceneEditWaitForSelector,
        viewportWidths: ['medium', 'wide', 'superwide'],
    },
}
EditSceneViewports.play = waitForFunnelToStabilize
