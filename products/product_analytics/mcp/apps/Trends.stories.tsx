import type { Meta, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { CHART_COLORS, CHART_THEME } from '@posthog/mcp-ui'
import { ChartDemoFrame } from '@posthog/mcp-ui/storybook/ChartDemoFrame'
import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'
import { TimeSeriesLineChart } from '@posthog/quill-charts'

import {
    buildTrendsLineTimeSeriesConfig,
    buildTrendsSeries,
    type TrendsResultLike,
} from '../../frontend/insights/trends/TrendsLineChart/trendsChartTransforms'

const getColor = (_r: TrendsResultLike, i: number): string => CHART_COLORS[i % CHART_COLORS.length]!

const DAYS = ['2025-05-26', '2025-05-27', '2025-05-28', '2025-05-29', '2025-05-30', '2025-05-31', '2025-06-01']

const meta: Meta = {
    title: 'MCP Apps/Trends',
    decorators: [McpThemeDecorator],
    parameters: {
        testOptions: {
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

function TrendsLineChartDemo({ results, isArea }: { results: TrendsResultLike[]; isArea?: boolean }): ReactElement {
    const series = buildTrendsSeries(results, { isArea, getColor })
    const config = buildTrendsLineTimeSeriesConfig({ results, isPercentStackView: false })
    return (
        <ChartDemoFrame>
            <TimeSeriesLineChart series={series} labels={DAYS} theme={CHART_THEME} config={config} />
        </ChartDemoFrame>
    )
}

export const SingleSeries: Story = {
    render: () => (
        <TrendsLineChartDemo
            results={[{ id: 1, label: 'Pageviews', data: [420, 380, 510, 490, 630, 580, 720], days: DAYS }]}
        />
    ),
    name: 'Single series',
}

export const MultiSeries: Story = {
    render: () => (
        <TrendsLineChartDemo
            results={[
                { id: 1, label: 'Pageviews', data: [420, 380, 510, 490, 630, 580, 720], days: DAYS },
                { id: 2, label: 'Signups', data: [42, 38, 51, 49, 63, 58, 72], days: DAYS },
                { id: 3, label: 'Purchases', data: [8, 12, 9, 15, 11, 18, 14], days: DAYS },
            ]}
        />
    ),
    name: 'Multi-series',
}

export const AreaChart: Story = {
    render: () => (
        <TrendsLineChartDemo
            results={[
                { id: 1, label: 'Pageviews', data: [420, 380, 510, 490, 630, 580, 720], days: DAYS },
                { id: 2, label: 'Signups', data: [42, 38, 51, 49, 63, 58, 72], days: DAYS },
            ]}
            isArea
        />
    ),
    name: 'Area chart',
}
