import { useMemo } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { Series, TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import { DataVisualizationNode } from '~/queries/schema/schema-general'

import { ContentAutopilotOpenInsightButton } from './ContentAutopilotOpenInsightButton'
import type { PromptVisibilityMetric } from './promptReport'
import type { EngineVisibilityChart } from './visibilityChart'

const BASE_CONFIG: TimeSeriesLineChartConfig = {
    xAxis: { interval: 'day' },
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
    mentioned: 'Share of answers that mention you',
    cited: 'Share of answers that cite you',
    position: 'Average position when cited',
}

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
    return (
        <PagePerformanceCard className="min-w-0">
            <PagePerformanceCardHeader
                description={description}
                title={TITLES[metric]}
                actions={
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonSegmentedButton
                            size="xsmall"
                            value={metric}
                            onChange={onMetricChange}
                            options={[
                                { value: 'mentioned', label: 'Mentioned' },
                                { value: 'cited', label: 'Cited' },
                                { value: 'position', label: 'Position' },
                            ]}
                            data-attr={`${dataAttr}-metric`}
                        />
                        <ContentAutopilotOpenInsightButton query={query} data-attr={`${dataAttr}-open-insight`} />
                    </div>
                }
            />
            <div className="h-72 min-w-0 flex flex-col p-2" data-attr={dataAttr}>
                <TimeSeriesLineChart
                    series={series}
                    labels={chart.labels}
                    theme={theme}
                    config={metric === 'position' ? POSITION_CONFIG : RATE_CONFIG}
                />
            </div>
        </PagePerformanceCard>
    )
}
