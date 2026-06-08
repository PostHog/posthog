import type { Meta, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'
import { ChartLegend, TimeSeriesBarChart, legendItemsFromSeries } from '@posthog/quill-charts'
import type { ChartTheme } from '@posthog/quill-charts'

import {
    buildTrendsLifecycleConfig,
    buildTrendsLifecycleSeries,
    type TrendsLifecycleResultLike,
} from '../../frontend/insights/trends/TrendsLifecycleChart/trendsLifecycleChartTransforms'

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

// Conventional lifecycle bucket colors — mirrors LifecycleVisualizer / --color-lifecycle-*.
const LIFECYCLE_COLORS: Record<string, string> = {
    new: '#1d4aff',
    returning: '#388600',
    resurrecting: '#a56eff',
    dormant: '#db3707',
}
const getColor = (status: string | undefined): string => LIFECYCLE_COLORS[status ?? 'new'] ?? '#1d4aff'

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

// Renders the chart the same way the MCP app does: assemble series + config, then hand them to quill.
// Fixed pixel size, not width:100% — the chart sizes its canvas off a ResizeObserver, which measures 0
// for a percentage width at mount in the headless snapshot runner and draws nothing.
function LifecycleChartDemo({
    results,
    isStacked,
}: {
    results: TrendsLifecycleResultLike[]
    isStacked: boolean
}): ReactElement {
    const series = buildTrendsLifecycleSeries(results, { getColor })
    const config = buildTrendsLifecycleConfig({ isStacked })
    const legendItems = legendItemsFromSeries(series, CHART_THEME)
    return (
        <ChartLegend show items={legendItems} position="top">
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div style={{ display: 'flex', flexDirection: 'column', width: 640, height: 320 }}>
                <TimeSeriesBarChart series={series} labels={LABELS} theme={CHART_THEME} config={config} />
            </div>
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
