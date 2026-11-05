import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { mswDecorator } from '~/mocks/browser'
import trendsPieBreakdownFixture from '~/mocks/fixtures/api/projects/team_id/insights/trendsPieBreakdown.json'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import { ChartDisplayType, type InsightLogicProps, type InsightShortId } from '~/types'

import { TrendsProportionBar } from './TrendsProportionBar'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/TrendsProportionBar',
    component: TrendsProportionBar,
    parameters: {
        layout: 'centered',
        mockDate: '2023-07-11',
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

function BreakdownProportionBar(): JSX.Element {
    const [dashboardItemId] = useState(() => `TrendsProportionBarStory.${uniqueNode++}` as InsightShortId)
    const source = trendsPieBreakdownFixture.query.source
    const cachedInsight: any = {
        ...trendsPieBreakdownFixture,
        short_id: dashboardItemId,
        query: {
            ...trendsPieBreakdownFixture.query,
            source: {
                ...source,
                trendsFilter: { ...source.trendsFilter, display: ChartDisplayType.ActionsProportionBar },
            },
        },
    }

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
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div style={{ height: 360, width: 720, display: 'flex', flexDirection: 'column' }}>
                    <TrendsProportionBar />
                </div>
            </BindLogic>
        </BindLogic>
    )
}

export const Breakdown: Story = {
    render: () => <BreakdownProportionBar />,
}
