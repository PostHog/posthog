import { useMemo } from 'react'

import { Empty, EmptyDescription, EmptyHeader, Text, ToggleGroup, ToggleGroupItem } from '@posthog/quill'
import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { Series, TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { pluralize } from 'lib/utils/strings'

import { DataVisualizationNode } from '~/queries/schema/schema-general'

import { AiVisibilityCard } from './AiVisibilityCard'
import { ContentAutopilotChartAverages } from './ContentAutopilotChartAverages'
import { ContentAutopilotOpenInsightButton } from './ContentAutopilotOpenInsightButton'
import type { PromptVisibilityMetric } from './promptReport'
import { type EngineVisibilityChart, MIN_TREND_DAYS, daysWithData, trendDisplay } from './visibilityChart'

const BASE_CONFIG: TimeSeriesLineChartConfig = {
    // The labels are calendar days, so UTC keeps each tick and tooltip date on its own day.
    xAxis: { interval: 'day', timezone: 'UTC' },
    legend: { show: true },
    showCrosshair: true,
    // Straight segments, because a curve invents values between days.
    curve: 'linear',
}

const RATE_CONFIG: TimeSeriesLineChartConfig = {
    ...BASE_CONFIG,
    yAxis: { format: 'percentage_scaled', showGrid: true },
}

const POSITION_CONFIG: TimeSeriesLineChartConfig = {
    ...BASE_CONFIG,
    yAxis: { format: 'numeric', decimalPlaces: 1, prefix: '#', showGrid: true },
}

const TITLES: Record<PromptVisibilityMetric, string> = {
    mentioned: 'Visibility',
    cited: 'Cited as a source',
    position: 'Average position when cited',
}

const EMPTY: Record<PromptVisibilityMetric, string> = {
    mentioned: 'No answers in this date range.',
    cited: 'No answers in this date range.',
    position: 'No answer in this date range cites you, so there is no position to show.',
}

const OPTIONS: { value: PromptVisibilityMetric; label: string }[] = [
    { value: 'mentioned', label: 'Visibility' },
    { value: 'cited', label: 'Cited' },
    { value: 'position', label: 'Position' },
]

/** One line per answer engine for the chosen metric, with a way to open the same numbers as an insight. */
export const ContentAutopilotVisibilityChart = ({
    chart,
    metric,
    onMetricChange,
    query,
    description,
    'data-attr': dataAttr,
}: {
    chart: EngineVisibilityChart
    metric: PromptVisibilityMetric
    onMetricChange: (metric: PromptVisibilityMetric) => void
    query: DataVisualizationNode
    description?: string
    'data-attr': string
}): JSX.Element => {
    const theme = useChartTheme()
    const series = useMemo<Series[]>(
        () => chart.series.map(({ engine, label, color, data }) => ({ key: engine, label, color, data })),
        [chart]
    )
    const hasData = chart.series.some(({ data }) => data.some(Number.isFinite))
    const days = daysWithData(chart)
    const display = trendDisplay(days)
    return (
        <AiVisibilityCard
            title={TITLES[metric]}
            description={description}
            actions={
                <>
                    <ToggleGroup
                        variant="outline"
                        aria-label="Chart metric"
                        value={[metric]}
                        onValueChange={(next: string[]) => {
                            // Clicking the chosen metric again empties the group, which keeps the current metric.
                            if (next[0]) {
                                onMetricChange(next[0] as PromptVisibilityMetric)
                            }
                        }}
                        data-attr={`${dataAttr}-metric`}
                    >
                        {OPTIONS.map(({ value, label }) => (
                            <ToggleGroupItem key={value} value={value}>
                                {label}
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                    <ContentAutopilotOpenInsightButton query={query} data-attr={`${dataAttr}-open-insight`} />
                </>
            }
        >
            {hasData && display === 'averages' ? (
                <ContentAutopilotChartAverages chart={chart} metric={metric} days={days} data-attr={dataAttr} />
            ) : (
                <div className="flex h-72 min-w-0 flex-col" data-attr={dataAttr}>
                    {hasData && display === 'waiting' ? (
                        <Text
                            size="xs"
                            variant="muted"
                            render={<p className="m-0 pb-1" />}
                            data-attr={`${dataAttr}-waiting`}
                        >
                            Waiting for more days of data. {pluralize(days, 'day')} of {MIN_TREND_DAYS} so far.
                        </Text>
                    ) : null}
                    {hasData ? (
                        <TimeSeriesLineChart
                            series={series}
                            labels={chart.labels}
                            theme={theme}
                            config={metric === 'position' ? POSITION_CONFIG : RATE_CONFIG}
                        />
                    ) : (
                        <Empty className="flex-1">
                            <EmptyHeader>
                                <EmptyDescription>{EMPTY[metric]}</EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    )}
                </div>
            )}
        </AiVisibilityCard>
    )
}
