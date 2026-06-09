import type { Meta, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { CHART_COLORS, CHART_THEME } from '@posthog/mcp-ui'
import { ChartDemoFrame } from '@posthog/mcp-ui/storybook/ChartDemoFrame'
import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'
import { TimeSeriesBarChart, TimeSeriesLineChart } from '@posthog/quill-charts'

import {
    buildRetentionBarChartConfig,
    buildRetentionLineChartConfig,
    buildRetentionSeries,
    type RetentionTrendSeriesEntry,
} from '../../frontend/insights/retention/shared/retentionChartTransforms'

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
        <ChartDemoFrame>
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
        </ChartDemoFrame>
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
