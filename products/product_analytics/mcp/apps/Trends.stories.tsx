import type { Meta, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { CHART_THEME, colorAt } from '@posthog/mcp-ui'
import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'
import { BarChart, TimeSeriesBarChart, TimeSeriesLineChart } from '@posthog/quill-charts'

import { buildTrendsBarChartModel } from '../../frontend/insights/trends/TrendsBarChart/trendsBarChartTransforms'
import {
    buildTrendsBarValueConfig,
    buildTrendsBarValueSeries,
    type TrendsBarValueItem,
} from '../../frontend/insights/trends/TrendsBarValueChart/trendsBarValueChartTransforms'
import {
    buildTrendsLineTimeSeriesConfig,
    buildTrendsSeries,
    type TrendsResultLike,
} from '../../frontend/insights/trends/TrendsLineChart/trendsChartTransforms'

const getColor = (_r: TrendsResultLike, i: number): string => colorAt(i)

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

// Renders the chart the same way the MCP app does: assemble series + config from results, then hand
// them to quill's TimeSeriesLineChart. Fixed pixel size, not width:100% — the chart sizes its canvas
// off a ResizeObserver, which measures 0 for a percentage width at mount in the headless snapshot
// runner and draws nothing.
function TrendsLineChartDemo({ results, isArea }: { results: TrendsResultLike[]; isArea?: boolean }): ReactElement {
    const series = buildTrendsSeries(results, { isArea, getColor })
    const config = buildTrendsLineTimeSeriesConfig({ results, isPercentStackView: false })
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'flex', flexDirection: 'column', width: 640, height: 300 }}>
            <TimeSeriesLineChart series={series} labels={DAYS} theme={CHART_THEME} config={config} />
        </div>
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

// Renders the line/bar toggle's bar mode the same way the MCP app does: time-series results through
// buildTrendsBarChartModel, then quill's TimeSeriesBarChart.
function TrendsBarChartDemo({ results }: { results: TrendsResultLike[] }): ReactElement {
    const { series, config } = buildTrendsBarChartModel(results, {
        getColor: (_r, i) => colorAt(i),
        labels: DAYS,
        isPercentStackView: false,
        isGrouped: false,
    })
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'flex', flexDirection: 'column', width: 640, height: 300 }}>
            <TimeSeriesBarChart series={series} labels={DAYS} theme={CHART_THEME} config={config} />
        </div>
    )
}

export const TimeSeriesBar: Story = {
    render: () => (
        <TrendsBarChartDemo
            results={[
                { id: 1, label: 'Pageviews', data: [420, 380, 510, 490, 630, 580, 720], days: DAYS },
                { id: 2, label: 'Signups', data: [42, 38, 51, 49, 63, 58, 72], days: DAYS },
            ]}
        />
    ),
    name: 'Time-series bar',
}

// Renders ActionsBarValue the same way the MCP app does: aggregated totals through
// buildTrendsBarValueSeries, then quill's BarChart. Fixed pixel size for the same
// headless-snapshot reason as the line demo above.
function TrendsBarValueChartDemo({
    items,
    height = 300,
}: {
    items: TrendsBarValueItem[]
    height?: number
}): ReactElement {
    const series = buildTrendsBarValueSeries(items, { getColor: colorAt })
    const config = buildTrendsBarValueConfig()
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'flex', flexDirection: 'column', width: 640, height }}>
            <BarChart series={series} labels={items.map((item) => item.label)} theme={CHART_THEME} config={config} />
        </div>
    )
}

export const BarValueFewSeries: Story = {
    render: () => (
        <TrendsBarValueChartDemo
            items={[
                { label: 'Chrome', value: 8421 },
                { label: 'Firefox', value: 3204 },
                { label: 'Safari', value: 2817 },
            ]}
        />
    ),
    name: 'Bar value — few series',
}

export const BarValueManyBreakdowns: Story = {
    render: () => (
        <TrendsBarValueChartDemo
            items={[
                { label: 'United States', value: 14320 },
                { label: 'United Kingdom', value: 6210 },
                { label: 'Germany', value: 4890 },
                { label: 'France', value: 3720 },
                { label: 'Canada', value: 2940 },
                { label: 'Australia', value: 2310 },
                { label: 'Netherlands', value: 1870 },
                { label: 'India', value: 1640 },
            ]}
            height={400}
        />
    ),
    name: 'Bar value — many breakdowns',
}
