import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'
import { TimeSeriesBarChart, useChartTheme, type TimeInterval } from '@posthog/quill-charts'

import { Section } from '../components/Section'
import { doraLogic } from './doraLogic'

export function DoraDeploymentFrequency(): JSX.Element {
    const { dora, doraLoading, environmentScopeLabel, frequencyCounts, frequencyIsoLabels } = useValues(doraLogic)
    const chartTheme = useChartTheme()
    const frequencySeries = useMemo(
        () => [{ key: 'deployments', label: 'Deployments', data: frequencyCounts }],
        [frequencyCounts]
    )

    return (
        <Section
            id="deployment-frequency"
            title="Deployments over time"
            note={`Successful deployments per bucket in the ${environmentScopeLabel} scope.`}
            busy={doraLoading && !!dora}
        >
            {doraLoading && !dora ? (
                <LemonSkeleton className="h-40 w-full" />
            ) : frequencyCounts.length === 0 ? (
                <div className="py-8 text-center text-sm text-secondary">No deploy data for this window.</div>
            ) : (
                // The chart's root is a `flex-1` child, so the sized wrapper must be a flex column.
                <div className="flex h-40 flex-col" data-attr="engineering-analytics-dora-frequency-chart">
                    <TimeSeriesBarChart
                        series={frequencySeries}
                        labels={frequencyIsoLabels}
                        theme={chartTheme}
                        config={{
                            xAxis: {
                                timezone: 'UTC',
                                interval: (dora?.series_granularity ?? 'day') as TimeInterval,
                            },
                            yAxis: { format: 'numeric', decimalPlaces: 0 },
                            minBarSize: 2,
                        }}
                    />
                </div>
            )}
        </Section>
    )
}
