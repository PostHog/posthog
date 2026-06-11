import type { Meta, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { CHART_THEME, colorAt } from '@posthog/mcp-ui'
import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'
import { TimeSeriesBarChart, TimeSeriesLineChart } from '@posthog/quill-charts'
import type { TooltipConfig } from '@posthog/quill-charts'

import {
    buildRetentionChartModel,
    type RetentionCohortLike,
} from '../../frontend/insights/retention/shared/retentionChartTransforms'

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
        getColor: colorAt,
        tooltip: TOOLTIP_CONFIG,
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

// More cohorts than palette colors — confirms nothing is truncated and colors wrap past the 15th.
const MANY_COHORTS: RetentionCohortLike[] = Array.from({ length: 18 }, (_, i) => {
    const day = String(i + 1).padStart(2, '0')
    const base = 100 + i * 5
    const retentionCurve = [1, 0.66, 0.5, 0.41, 0.31]
    return {
        date: `2024-05-${day}`,
        values: retentionCurve.map((ratio) => ({ count: Math.round(base * ratio) })),
    }
})

export const ManyCohorts: Story = {
    render: () => <RetentionChartDemo cohorts={MANY_COHORTS} mode="line" />,
    name: 'Many cohorts',
}
