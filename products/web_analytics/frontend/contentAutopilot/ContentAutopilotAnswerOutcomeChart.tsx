import { useMemo } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { TimeSeriesBarChart } from '@posthog/quill-charts'
import type { Series, TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import { DataVisualizationNode } from '~/queries/schema/schema-general'

import { ContentAutopilotOpenInsightButton } from './ContentAutopilotOpenInsightButton'
import type { PromptOutcomeMetric } from './promptReport'
import type { AnswerOutcomeChart } from './visibilityChart'

const CONFIG: TimeSeriesBarChartConfig = {
    xAxis: { interval: 'day' },
    yAxis: { format: 'numeric', showGrid: true },
    legend: { show: true },
    barLayout: 'stacked',
}

const COPY: Record<PromptOutcomeMetric, { title: string; yes: string; no: string }> = {
    mentioned: { title: 'Answers that mention you', yes: 'Mentioned', no: 'Not mentioned' },
    cited: { title: 'Answers that cite you', yes: 'Cited', no: 'Not cited' },
}

/** One stacked bar per day: the answers that met the metric on top of the ones that didn't, across every engine. */
export const ContentAutopilotAnswerOutcomeChart = ({
    chart,
    metric,
    onMetricChange,
    query,
    description,
    'data-attr': dataAttr,
}: {
    chart: AnswerOutcomeChart
    metric: PromptOutcomeMetric
    onMetricChange: (metric: PromptOutcomeMetric) => void
    query: DataVisualizationNode
    description?: string
    'data-attr': string
}): JSX.Element => {
    const theme = useChartTheme()
    // The same colors as the result dots in the answer tables. Read on every render so they follow the color mode.
    const yesColor = getColorVar('success')
    const noColor = getColorVar('color-text-tertiary')
    const series = useMemo<Series[]>(
        () => [
            { key: 'yes', label: COPY[metric].yes, color: yesColor, data: chart.yes },
            { key: 'no', label: COPY[metric].no, color: noColor, data: chart.no },
        ],
        [chart, metric, yesColor, noColor]
    )
    return (
        <PagePerformanceCard className="min-w-0">
            <PagePerformanceCardHeader
                description={description}
                title={COPY[metric].title}
                actions={
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonSegmentedButton
                            size="xsmall"
                            value={metric}
                            onChange={onMetricChange}
                            options={[
                                { value: 'mentioned', label: 'Mentioned' },
                                { value: 'cited', label: 'Cited' },
                            ]}
                            data-attr={`${dataAttr}-metric`}
                        />
                        <ContentAutopilotOpenInsightButton query={query} data-attr={`${dataAttr}-open-insight`} />
                    </div>
                }
            />
            <div className="h-72 min-w-0 flex flex-col p-2" data-attr={dataAttr}>
                <TimeSeriesBarChart series={series} labels={chart.labels} theme={theme} config={CONFIG} />
            </div>
        </PagePerformanceCard>
    )
}
