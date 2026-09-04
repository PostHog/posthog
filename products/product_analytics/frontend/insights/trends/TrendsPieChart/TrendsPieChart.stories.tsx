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
import { ChartDisplayType, type InsightLogicProps, type InsightShortId } from '~/types'

import { TrendsPieChart } from './TrendsPieChart'

// Legend stories need enough slices for the legend to claim real space; the base fixture has
// three, so pad it with invented breakdown values.
const manySliceResult = (trendsPieBreakdownFixture as any).result.flatMap((item: any, index: number) =>
    [0, 1, 2].map((copy) => ({
        ...item,
        label: `$pageview - ${item.breakdown_value ?? index}-v${copy}`,
        breakdown_value: `${item.breakdown_value ?? index}-v${copy}`,
        aggregated_value: Math.round(item.aggregated_value / (copy + 2)),
    }))
)

// No insight sets an explicit legendPosition, so the in-app default is the right-hand side.
const trendsPieBreakdownWithLegendFixture = {
    ...trendsPieBreakdownFixture,
    result: manySliceResult,
    query: {
        ...trendsPieBreakdownFixture.query,
        source: {
            ...trendsPieBreakdownFixture.query.source,
            trendsFilter: { ...trendsPieBreakdownFixture.query.source.trendsFilter, showLegend: true },
        },
    },
}

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

// Dashboard-tile width — below the side-legend threshold, so a legend pinned to the side moves
// below the pie instead of splitting the tile with it.
function NarrowStage({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ height: 360, width: 300, display: 'flex', flexDirection: 'column' }}>{children}</div>
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

export const Donut: Story = {
    render: () =>
        renderTrendsPieChart({
            ...trendsPieBreakdownFixture,
            query: {
                ...trendsPieBreakdownFixture.query,
                source: {
                    ...trendsPieBreakdownFixture.query.source,
                    trendsFilter: {
                        ...trendsPieBreakdownFixture.query.source.trendsFilter,
                        display: ChartDisplayType.ActionsDonut,
                    },
                },
            },
        }),
}

function renderBreakdownPieWithFilter(trendsFilter: Record<string, unknown>): JSX.Element {
    return renderTrendsPieChart({
        ...trendsPieBreakdownFixture,
        query: {
            ...trendsPieBreakdownFixture.query,
            source: {
                ...trendsPieBreakdownFixture.query.source,
                trendsFilter: { ...trendsPieBreakdownFixture.query.source.trendsFilter, ...trendsFilter },
            },
        },
    })
}

export const BreakdownWithLabels: Story = {
    render: () => renderBreakdownPieWithFilter({ showLabelsOnSeries: true, showValuesOnSeries: true }),
}

export const BreakdownWithValueAndPercentage: Story = {
    render: () =>
        renderBreakdownPieWithFilter({
            showLabelsOnSeries: true,
            showValuesOnSeries: true,
            showPercentStackView: true,
        }),
}

// The dashboard-tile case: the side legend would take close to half this width, so it renders
// below the pie instead.
export const LegendOnNarrowTile: Story = {
    render: () => renderTrendsPieChart(trendsPieBreakdownWithLegendFixture, NarrowStage),
}

// On a wide surface the same insight keeps the legend at its configured right-hand side.
export const LegendOnWideSurface: Story = {
    render: () => renderTrendsPieChart(trendsPieBreakdownWithLegendFixture),
}
