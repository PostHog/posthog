import type { Meta, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { CHART_THEME, lifecycleColor } from '@posthog/mcp-ui'
import { ChartDemoFrame } from '@posthog/mcp-ui/storybook/ChartDemoFrame'
import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'
import { ChartLegend, TimeSeriesBarChart, legendItemsFromSeries } from '@posthog/quill-charts'

import {
    buildTrendsLifecycleConfig,
    buildTrendsLifecycleSeries,
    type TrendsLifecycleResultLike,
} from '../../frontend/insights/trends/TrendsLifecycleChart/trendsLifecycleChartTransforms'

const LABELS = ['Jun 1', 'Jun 2', 'Jun 3', 'Jun 4', 'Jun 5', 'Jun 6', 'Jun 7']

// `dormant` values come back negated from the backend so a diverging stack lays them below zero.
const RESULTS: TrendsLifecycleResultLike[] = [
    { id: 'new', status: 'new', label: 'Pageview - new', data: [40, 35, 50, 45, 60, 55, 70] },
    { id: 'returning', status: 'returning', label: 'Pageview - returning', data: [20, 30, 35, 40, 45, 50, 55] },
    { id: 'resurrecting', status: 'resurrecting', label: 'Pageview - resurrecting', data: [10, 8, 12, 9, 14, 11, 16] },
    { id: 'dormant', status: 'dormant', label: 'Pageview - dormant', data: [-15, -20, -18, -25, -22, -30, -28] },
]

const meta: Meta = {
    title: 'MCP Apps/Lifecycle',
    decorators: [McpThemeDecorator],
    parameters: {
        testOptions: {
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

function LifecycleChartDemo({
    results,
    isStacked,
}: {
    results: TrendsLifecycleResultLike[]
    isStacked: boolean
}): ReactElement {
    const series = buildTrendsLifecycleSeries(results, { getColor: lifecycleColor })
    const config = buildTrendsLifecycleConfig({ isStacked })
    const legendItems = legendItemsFromSeries(series, CHART_THEME)
    return (
        <ChartLegend show items={legendItems} position="top">
            <ChartDemoFrame>
                <TimeSeriesBarChart series={series} labels={LABELS} theme={CHART_THEME} config={config} />
            </ChartDemoFrame>
        </ChartLegend>
    )
}

export const Stacked: Story = {
    render: () => <LifecycleChartDemo results={RESULTS} isStacked />,
    name: 'Stacked',
}

export const Grouped: Story = {
    render: () => <LifecycleChartDemo results={RESULTS} isStacked={false} />,
    name: 'Grouped',
}
