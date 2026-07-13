import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import {
    createInsightStory,
    insightSceneMswDecorator,
    insightSceneStoryParameters,
} from 'scenes/insights/__mocks__/createInsightScene'
import { insightLogic } from 'scenes/insights/insightLogic'

import funnelTimeToConvertFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvert.json'
import funnelTimeToConvertCompareFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvertCompare.json'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import { InsightLogicProps, InsightShortId } from '~/types'

import { FunnelHistogramChart } from './FunnelHistogramChart'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/FunnelHistogramChart',
    component: FunnelHistogramChart,
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
        <div style={{ height: 360, width: 720, display: 'flex', flexDirection: 'column' }}>{children}</div>
    )
}

function renderFunnelHistogramChart(insightFixture: any): JSX.Element {
    const [dashboardItemId] = useState(() => `FunnelHistogramChartStory.${uniqueNode++}` as InsightShortId)
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
                    <FunnelHistogramChart />
                </Stage>
            </BindLogic>
        </BindLogic>
    )
}

export const Default: Story = {
    render: () => renderFunnelHistogramChart(funnelTimeToConvertFixture),
}

export const Compare: Story = {
    render: () => renderFunnelHistogramChart(funnelTimeToConvertCompareFixture),
}

// Full insight scene in edit mode — the time-to-convert editor
export const EditScene: Story = createInsightStory(funnelTimeToConvertFixture as any, 'edit')
EditScene.decorators = [insightSceneMswDecorator]
EditScene.parameters = {
    ...insightSceneStoryParameters,
    testOptions: {
        ...insightSceneStoryParameters.testOptions,
        waitForSelector: '[data-attr=funnel-histogram] canvas[role="img"]',
    },
}
