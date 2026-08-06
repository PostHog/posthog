import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { insightLogic } from 'scenes/insights/insightLogic'

import { mswDecorator } from '~/mocks/browser'
import trendsPieFixture from '~/mocks/fixtures/api/projects/team_id/insights/trendsPie.json'
import trendsPieBreakdownFixture from '~/mocks/fixtures/api/projects/team_id/insights/trendsPieBreakdown.json'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import type { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import type { InsightLogicProps, InsightShortId } from '~/types'

import { TrendsPieChart } from './TrendsPieChart'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/TrendsPieChart',
    component: TrendsPieChart,
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

// Mirrors the production layout (`.TrendsInsight`): a flex column whose height comes from
// `min-height` only, with no explicit `height`. A wrapper relying on `h-full` collapses to 0
// here and the pie renders no slices — this stage guards that regression.
function MinHeightStage({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ minHeight: 360, width: 720, display: 'flex', flexDirection: 'column' }}>{children}</div>
    )
}

function renderTrendsPieChart(insightFixture: any, StageComponent: typeof Stage = Stage): JSX.Element {
    const [dashboardItemId] = useState(() => `TrendsPieChartStory.${uniqueNode++}` as InsightShortId)
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
                <StageComponent>
                    <TrendsPieChart />
                </StageComponent>
            </BindLogic>
        </BindLogic>
    )
}

export const Default: Story = {
    render: () => renderTrendsPieChart(trendsPieFixture),
}

export const Breakdown: Story = {
    render: () => renderTrendsPieChart(trendsPieBreakdownFixture),
}

// Parent supplies height via `min-height` only (as `.TrendsInsight` does) — verifies the chart
// still sizes itself and renders slices rather than collapsing to the bare aggregation total.
export const MinHeightParent: Story = {
    render: () => renderTrendsPieChart(trendsPieBreakdownFixture, MinHeightStage),
}

export const BreakdownWithLabels: Story = {
    render: () =>
        renderTrendsPieChart({
            ...trendsPieBreakdownFixture,
            query: {
                ...trendsPieBreakdownFixture.query,
                source: {
                    ...trendsPieBreakdownFixture.query.source,
                    trendsFilter: {
                        ...trendsPieBreakdownFixture.query.source.trendsFilter,
                        showLabelOnSeries: true,
                        showValuesOnSeries: true,
                    },
                },
            },
        }),
}
