import { useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonSegmentedButton, type LemonSegmentedButtonOption, LemonTag } from '@posthog/lemon-ui'
import {
    Heatmap,
    type HeatmapConfig,
    type Series,
    SlopeChart,
    type SlopeChartConfig,
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
} from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

export type ClassifierVisualization = 'volume' | 'share' | 'change' | 'timeline'

export interface ReplayVisionClassifierVisualizationPrototypeProps {
    initialVisualization: ClassifierVisualization
    dateLabels: string[]
    series: Series[]
    changeLabels: string[]
    changeSeries: Series[]
    timelineDateLabels: string[]
    timelineCategoryLabels: string[]
    timelineCells: number[][]
    observationCount: number
    configuredCategoryCount: number
    discoveredCategory: string
    discoveredCategoryDate: string
}

// Changing these data-attr values breaks autocapture dashboards and visual tests.
const VISUALIZATION_OPTIONS: LemonSegmentedButtonOption<ClassifierVisualization>[] = [
    {
        value: 'volume',
        label: 'Volume',
        tooltip: 'How many sessions were assigned to each category each week',
        'data-attr': 'replay-vision-classifier-visualization-volume',
    },
    {
        value: 'share',
        label: 'Share',
        tooltip: 'How each category contributes to weekly category assignments',
        'data-attr': 'replay-vision-classifier-visualization-share',
    },
    {
        value: 'change',
        label: 'Change',
        tooltip: 'Which categories grew or shrank between two periods',
        'data-attr': 'replay-vision-classifier-visualization-change',
    },
    {
        value: 'timeline',
        label: 'Timeline',
        tooltip: 'When categories appeared, persisted, or faded',
        'data-attr': 'replay-vision-classifier-visualization-timeline',
    },
]

const VISUALIZATION_DESCRIPTIONS: Record<ClassifierVisualization, string> = {
    volume: 'Weekly observation counts show category growth alongside changes in scanner volume.',
    share: 'Each week is normalized to 100% so scanner volume does not affect the category mix.',
    change: 'The previous and current four-week periods show which categories gained or lost assignment share.',
    timeline: "Color intensity shows each category's share of assignments and makes appearance or fading visible.",
}

const VOLUME_CONFIG: TimeSeriesLineChartConfig = {
    xAxis: { timezone: 'UTC', interval: 'week' },
    yAxis: { format: 'short', showGrid: true },
    legend: { show: true, position: 'bottom' },
    tooltip: { showTotal: true, totalLabel: 'Observed sessions' },
}

const SHARE_CONFIG: TimeSeriesBarChartConfig = {
    barLayout: 'percent',
    bandPadding: 0.24,
    xAxis: { timezone: 'UTC', interval: 'week' },
    yAxis: { format: 'percentage_scaled', showGrid: true },
    legend: { show: true, position: 'bottom' },
    tooltip: { showTotal: true, totalLabel: 'Observed sessions' },
}

const CHANGE_CONFIG: SlopeChartConfig = {
    showSeriesLabels: false,
    legend: { show: true, position: 'bottom' },
    valueFormatter: (value: number): string => `${value}%`,
    deltaFormatter: (delta: number): string => `${delta > 0 ? '+' : ''}${delta} points`,
}

const TIMELINE_CONFIG: HeatmapConfig = {
    colorScale: 'linear',
    xTickFormatter: (label: string, index: number): string | null => (index % 2 === 0 ? label : null),
    tooltip: { valueFormatter: (value: number): string => `${value}% of category assignments` },
}

const CHART_DATA_ATTR = 'replay-vision-classifier-visualization-chart'

export function ReplayVisionClassifierVisualizationPrototype({
    initialVisualization,
    dateLabels,
    series,
    changeLabels,
    changeSeries,
    timelineDateLabels,
    timelineCategoryLabels,
    timelineCells,
    observationCount,
    configuredCategoryCount,
    discoveredCategory,
    discoveredCategoryDate,
}: ReplayVisionClassifierVisualizationPrototypeProps): JSX.Element {
    const theme = useChartTheme()
    const [visualization, setVisualization] = useState<ClassifierVisualization>(initialVisualization)

    const chart = (): JSX.Element => {
        if (visualization === 'volume') {
            return (
                <TimeSeriesLineChart
                    dataAttr={CHART_DATA_ATTR}
                    labels={dateLabels}
                    series={series}
                    theme={theme}
                    config={VOLUME_CONFIG}
                />
            )
        }
        if (visualization === 'share') {
            return (
                <TimeSeriesBarChart
                    dataAttr={CHART_DATA_ATTR}
                    labels={dateLabels}
                    series={series}
                    theme={theme}
                    config={SHARE_CONFIG}
                />
            )
        }
        if (visualization === 'change') {
            return (
                <SlopeChart
                    dataAttr={CHART_DATA_ATTR}
                    labels={changeLabels}
                    series={changeSeries}
                    theme={theme}
                    config={CHANGE_CONFIG}
                />
            )
        }
        return (
            <Heatmap
                dataAttr={CHART_DATA_ATTR}
                xLabels={timelineDateLabels}
                yLabels={timelineCategoryLabels}
                cells={timelineCells}
                theme={theme}
                config={TIMELINE_CONFIG}
            />
        )
    }

    return (
        <div className="@container/classifier-visualization rounded border bg-surface-primary p-4 space-y-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <h2 className="m-0 text-sm font-semibold">Category mix over time</h2>
                        <LemonTag type="muted">Dummy data</LemonTag>
                    </div>
                    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted tabular-nums">
                        <span>{observationCount.toLocaleString()} observations</span>
                        <span>{configuredCategoryCount} configured categories</span>
                        <span>1 freeform category</span>
                    </div>
                </div>
                <div className="w-full max-w-2xl">
                    <LemonSegmentedButton
                        fullWidth
                        size="xsmall"
                        value={visualization}
                        onChange={setVisualization}
                        options={VISUALIZATION_OPTIONS}
                    />
                </div>
            </div>

            <div className="h-96 flex flex-col">{chart()}</div>

            <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
                <p className="m-0 max-w-3xl text-xs text-muted">{VISUALIZATION_DESCRIPTIONS[visualization]}</p>
                <LemonTag type="highlight" icon={<IconSparkles />}>
                    {discoveredCategory} first observed {discoveredCategoryDate}
                </LemonTag>
            </div>
        </div>
    )
}
