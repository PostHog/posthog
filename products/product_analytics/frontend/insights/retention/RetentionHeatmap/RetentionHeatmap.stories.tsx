import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { mswDecorator } from '~/mocks/browser'
import retentionFixture from '~/mocks/fixtures/api/projects/team_id/insights/retention.json'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import type { InsightLogicProps, InsightShortId } from '~/types'

import { realisticRetentionResult } from '../shared/retentionStoryFixtures'
import { RetentionHeatmap } from './RetentionHeatmap'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/RetentionHeatmap',
    component: RetentionHeatmap,
    parameters: {
        layout: 'centered',
        mockDate: '2023-07-11',
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

function renderRetentionHeatmap(insightFixture: any): JSX.Element {
    const [dashboardItemId] = useState(() => `RetentionHeatmapStory.${uniqueNode++}` as InsightShortId)
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
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div style={{ width: 860 }}>
                    <RetentionHeatmap />
                </div>
            </BindLogic>
        </BindLogic>
    )
}

export const Default: Story = {
    render: () => renderRetentionHeatmap(retentionFixture),
}

export const RealisticCurve: Story = {
    render: () => renderRetentionHeatmap({ ...retentionFixture, result: realisticRetentionResult }),
}
