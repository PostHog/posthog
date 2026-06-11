import type { Meta, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'
import { TimeSeriesBarChart, TimeSeriesLineChart } from '@posthog/quill-charts'
import type { ChartTheme, TooltipConfig } from '@posthog/quill-charts'

import {
    buildRetentionChartModel,
    type RetentionCohortLike,
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

// Matches the config RetentionVisualizer passes, so the snapshot reflects the real component.
const TOOLTIP_CONFIG: TooltipConfig = { pinnable: true, placement: 'top' }

// Raw per-interval counts per cohort; buildRetentionChartModel derives the retention percentages,
// labels, and y-axis exactly as the visualizer does.
const COHORTS: RetentionCohortLike[] = [
    { date: '2024-05-26', values: [100, 64, 48, 39, 30].map((count) => ({ count })) },
    { date: '2024-05-27', values: [120, 85, 66, 53, 43].map((count) => ({ count })) },
    { date: '2024-05-28', values: [90, 52, 37, 30, 23].map((count) => ({ count })) },
]

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

function RetentionChartDemo({ cohorts, mode }: { cohorts: RetentionCohortLike[]; mode: 'line' | 'bar' }): ReactElement {
    const model = buildRetentionChartModel(cohorts, {
        aggregationType: 'count',
        reference: 'total',
        period: 'Day',
        getColor: (i) => CHART_COLORS[i % CHART_COLORS.length]!,
        tooltip: TOOLTIP_CONFIG,
        maxCohorts: CHART_COLORS.length,
    })
    return (
        // Fixed pixel size, not w-full — the chart sizes its canvas off a ResizeObserver, which measures 0
        // for a percentage width at mount in the headless snapshot runner and draws nothing.
        <div className="flex flex-col w-[640px] h-[320px]">
            {mode === 'bar' ? (
                <TimeSeriesBarChart
                    series={model.series}
                    labels={model.labels}
                    theme={CHART_THEME}
                    config={model.barConfig}
                />
            ) : (
                <TimeSeriesLineChart
                    series={model.series}
                    labels={model.labels}
                    theme={CHART_THEME}
                    config={model.lineConfig}
                />
            )}
        </div>
    )
}

export const LineChart: Story = {
    render: () => <RetentionChartDemo cohorts={COHORTS} mode="line" />,
    name: 'Line chart',
}

export const BarChart: Story = {
    render: () => <RetentionChartDemo cohorts={COHORTS} mode="bar" />,
    name: 'Bar chart',
}

export const SingleCohort: Story = {
    render: () => <RetentionChartDemo cohorts={[COHORTS[0]!]} mode="line" />,
    name: 'Single cohort',
}
