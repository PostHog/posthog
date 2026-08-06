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
import { RetentionBarChart } from './RetentionBarChart'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/RetentionBarChart',
    component: RetentionBarChart,
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

function Stage({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ height: 360, width: 720, display: 'flex', flexDirection: 'column' }}>{children}</div>
    )
}

function renderRetentionBarChart(insightFixture: any): JSX.Element {
    const [dashboardItemId] = useState(() => `RetentionBarChartStory.${uniqueNode++}` as InsightShortId)
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
                    <RetentionBarChart />
                </Stage>
            </BindLogic>
        </BindLogic>
    )
}

// Build a bar-display variant from the retention fixture
const retentionBarFixture = {
    ...retentionFixture,
    query: {
        ...retentionFixture.query,
        source: {
            ...retentionFixture.query.source,
            retentionFilter: {
                ...(retentionFixture.query.source as any).retentionFilter,
                display: 'ActionsBar',
            },
        },
    },
}

export const Default: Story = {
    render: () => renderRetentionBarChart(retentionBarFixture),
}

const realisticBarFixture = {
    ...retentionBarFixture,
    result: realisticRetentionResult,
}

export const RealisticCurve: Story = {
    render: () => renderRetentionBarChart(realisticBarFixture),
}
