import type { Meta, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'
import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { ChartTheme } from '@posthog/quill-charts'

import {
    buildTrendsLineTimeSeriesConfig,
    buildTrendsSeries,
    type TrendsResultLike,
} from '../../frontend/insights/trends/TrendsLineChart/trendsChartTransforms'

// PostHog brand palette — mirrors services/mcp/src/ui-apps/components/charts/theme.ts
const CHART_COLORS = ['#1d4aff', '#621da6', '#00d683', '#f54e00', '#f7a501', '#dc2626']

const CHART_THEME: ChartTheme = {
    colors: CHART_COLORS,
    backgroundColor: '#ffffff',
    axisColor: '#9ca3af',
    gridColor: 'rgba(128,128,128,0.2)',
    crosshairColor: 'rgba(128,128,128,0.5)',
    tooltipBackground: '#ffffff',
    tooltipColor: '#111827',
}

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
