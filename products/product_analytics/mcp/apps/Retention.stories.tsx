import type { Meta, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'
import { TimeSeriesBarChart, TimeSeriesLineChart } from '@posthog/quill-charts'
import type { ChartTheme } from '@posthog/quill-charts'

import {
    buildRetentionBarChartConfig,
    buildRetentionLineChartConfig,
    buildRetentionSeries,
    type RetentionTrendSeriesEntry,
} from '../../frontend/insights/retention/shared/retentionChartTransforms'

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

// Three cohorts measured over five intervals — each `data` value is a retention percentage (0..100).
const COHORTS: RetentionTrendSeriesEntry[] = [
    {
        count: 100,
        data: [100, 64, 48, 39, 30],
        labels: ['Day 0', 'Day 1', 'Day 2', 'Day 3', 'Day 4'],
        index: 0,
        label: 'Cohort 1 (May 26)',
    },
    {
        count: 120,
        data: [100, 71, 55, 44, 36],
        labels: ['Day 0', 'Day 1', 'Day 2', 'Day 3', 'Day 4'],
        index: 1,
        label: 'Cohort 2 (May 27)',
    },
    {
        count: 90,
        data: [100, 58, 41, 33, 25],
        labels: ['Day 0', 'Day 1', 'Day 2', 'Day 3', 'Day 4'],
        index: 2,
        label: 'Cohort 3 (May 28)',
    },
]

const LABELS = ['Day 0', 'Day 1', 'Day 2', 'Day 3', 'Day 4']

const meta: Meta = {
    title: 'MCP Apps/Retention',
    decorators: [McpThemeDecorator],
    parameters: {
        testOptions: {
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

// Renders the chart the same way the MCP app does: assemble series + config from cohort entries, then
// hand them to quill. Fixed pixel size, not width:100% — the chart sizes its canvas off a
// ResizeObserver, which measures 0 for a percentage width at mount in the headless snapshot runner.
function RetentionChartDemo({
    entries,
    mode,
}: {
    entries: RetentionTrendSeriesEntry[]
    mode: 'line' | 'bar'
}): ReactElement {
    const series = buildRetentionSeries(entries, { isIntervalView: false }).map((s, i) => ({
        ...s,
        color: CHART_COLORS[i % CHART_COLORS.length]!,
    }))
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'flex', flexDirection: 'column', width: 640, height: 320 }}>
            {mode === 'bar' ? (
                <TimeSeriesBarChart
                    series={series}
                    labels={LABELS}
                    theme={CHART_THEME}
                    config={buildRetentionBarChartConfig({ isPercentage: true, series })}
                />
            ) : (
                <TimeSeriesLineChart
                    series={series}
                    labels={LABELS}
                    theme={CHART_THEME}
                    config={buildRetentionLineChartConfig({ isPercentage: true, series })}
                />
            )}
        </div>
    )
}

export const LineChart: Story = {
    render: () => <RetentionChartDemo entries={COHORTS} mode="line" />,
    name: 'Line chart',
}

export const BarChart: Story = {
    render: () => <RetentionChartDemo entries={COHORTS} mode="bar" />,
    name: 'Bar chart',
}

export const SingleCohort: Story = {
    render: () => <RetentionChartDemo entries={[COHORTS[0]!]} mode="line" />,
    name: 'Single cohort',
}
