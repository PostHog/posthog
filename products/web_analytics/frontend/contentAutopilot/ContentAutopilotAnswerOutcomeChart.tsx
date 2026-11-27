import { useMemo } from 'react'

import { Empty, EmptyDescription, EmptyHeader, ToggleGroup, ToggleGroupItem } from '@posthog/quill'
import { TimeSeriesBarChart } from '@posthog/quill-charts'
import type { Series, TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'

import { DataVisualizationNode } from '~/queries/schema/schema-general'

import { AiVisibilityCard } from './AiVisibilityCard'
import { ContentAutopilotOpenInsightButton } from './ContentAutopilotOpenInsightButton'
import type { PromptOutcomeMetric } from './promptReport'
import type { AnswerOutcomeChart } from './visibilityChart'

const CONFIG: TimeSeriesBarChartConfig = {
    // The labels are calendar days, so UTC keeps each tick and tooltip date on its own day.
    xAxis: { interval: 'day', timezone: 'UTC' },
    yAxis: { format: 'numeric', showGrid: true },
    legend: { show: true },
    barLayout: 'stacked',
}

const COPY: Record<PromptOutcomeMetric, { title: string; yes: string; no: string }> = {
    mentioned: { title: 'Answers that mention you', yes: 'Mentioned', no: 'Not mentioned' },
    cited: { title: 'Answers that cite you', yes: 'Cited', no: 'Not cited' },
}

const OPTIONS: { value: PromptOutcomeMetric; label: string }[] = [
    { value: 'mentioned', label: 'Mentioned' },
    { value: 'cited', label: 'Cited' },
]

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
    const hasData = chart.yes.some(Boolean) || chart.no.some(Boolean)
    return (
        <AiVisibilityCard
            title={COPY[metric].title}
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
                                onMetricChange(next[0] as PromptOutcomeMetric)
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
            <div className="flex h-72 min-w-0 flex-col" data-attr={dataAttr}>
                {hasData ? (
                    <TimeSeriesBarChart series={series} labels={chart.labels} theme={theme} config={CONFIG} />
                ) : (
                    <Empty className="flex-1">
                        <EmptyHeader>
                            <EmptyDescription>No answers in this date range.</EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                )}
            </div>
        </AiVisibilityCard>
    )
}
