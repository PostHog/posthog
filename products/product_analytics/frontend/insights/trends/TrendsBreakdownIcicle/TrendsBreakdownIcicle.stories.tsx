import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { mswDecorator } from '~/mocks/browser'
import trendsBreakdownIcicleFixture from '~/mocks/fixtures/api/projects/team_id/insights/trendsBreakdownIcicle.json'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import type { InsightLogicProps, InsightShortId } from '~/types'

import { TrendsBreakdownIcicle } from './TrendsBreakdownIcicle'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/TrendsBreakdownIcicle',
    component: TrendsBreakdownIcicle,
    parameters: {
        layout: 'centered',
        mockDate: '2024-06-10',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/annotations/': { count: 0, next: null, previous: null, results: [] },
            },
        }),
    ],
}
export default meta

let uniqueNode = 0

function CountryThenBrowserIcicle(): JSX.Element {
    const [dashboardItemId] = useState(() => `TrendsBreakdownIcicleStory.${uniqueNode++}` as InsightShortId)
    const cachedInsight: any = { ...trendsBreakdownIcicleFixture, short_id: dashboardItemId }
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
                <div className="flex flex-col w-[960px] h-[320px]">
                    <TrendsBreakdownIcicle />
                </div>
            </BindLogic>
        </BindLogic>
    )
}

export const CountryThenBrowser: Story = {
    render: () => <CountryThenBrowserIcicle />,
}
