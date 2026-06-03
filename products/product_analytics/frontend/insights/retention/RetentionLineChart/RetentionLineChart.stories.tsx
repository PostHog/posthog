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

import { RetentionLineChart } from './RetentionLineChart'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/RetentionLineChart',
    component: RetentionLineChart,
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

function renderRetentionLineChart(insightFixture: any): JSX.Element {
    const [dashboardItemId] = useState(() => `RetentionLineChartStory.${uniqueNode++}` as InsightShortId)
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
                    <RetentionLineChart />
                </Stage>
            </BindLogic>
        </BindLogic>
    )
}

export const Default: Story = {
    render: () => renderRetentionLineChart(retentionFixture),
}

// Realistic retention curve for a richer visual
const retentionCurve = [1.0, 0.58, 0.42, 0.32, 0.26, 0.22, 0.18, 0.15]
const cohortSeeds = [1024, 1150, 980, 870, 1320, 1080, 940, 760]
const realisticResult = cohortSeeds.map((seed, cohortIndex) => {
    const periodCount = Math.max(1, cohortSeeds.length - cohortIndex)
    const jitter = 1 + ((cohortIndex % 3) - 1) * 0.04
    return {
        label: `Day ${cohortIndex}`,
        date: `2023-07-${String(cohortIndex + 1).padStart(2, '0')}T00:00:00Z`,
        values: retentionCurve.slice(0, Math.min(periodCount, retentionCurve.length)).map((r, i) => ({
            count: i === 0 ? seed : Math.round(seed * r * jitter),
            people: [],
        })),
        people_url: '',
    }
})

const realisticFixture = {
    ...retentionFixture,
    result: realisticResult,
}

export const RealisticCurve: Story = {
    render: () => renderRetentionLineChart(realisticFixture),
}
