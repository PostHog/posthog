import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { dataNodeLogic } from '@posthog/query-frontend/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '@posthog/query-frontend/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '@posthog/query-frontend/nodes/InsightViz/InsightViz'
import { getCachedResults } from '@posthog/query-frontend/nodes/InsightViz/utils'

import { insightLogic } from 'scenes/insights/insightLogic'

import funnelTimeToConvertFixture from '~/mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvert.json'
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
