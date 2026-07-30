import { useValues } from 'kea'
import { useMemo } from 'react'

import { getColorVar } from 'lib/colors'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'

import { WORKFLOW_PUSH_METRICS } from './workflowMetricsSummaryLogic'

const PUSH_METRIC_KEYS = Object.keys(WORKFLOW_PUSH_METRICS) as (keyof typeof WORKFLOW_PUSH_METRICS)[]

export function PushMetricsSummary({ logicKey }: { logicKey: string }): JSX.Element {
    const { appMetricsTrendsLoading, appMetricsTrends, getSingleTrendSeries } = useValues(appMetricsLogic({ logicKey }))

    const pushTrends = useMemo(
        () =>
            appMetricsTrends
                ? {
                      ...appMetricsTrends,
                      series: appMetricsTrends.series
                          .filter((series) => series.name in WORKFLOW_PUSH_METRICS)
                          .map((series) => ({
                              ...series,
                              name:
                                  WORKFLOW_PUSH_METRICS[series.name as keyof typeof WORKFLOW_PUSH_METRICS]?.name ??
                                  series.name,
                              color: WORKFLOW_PUSH_METRICS[series.name as keyof typeof WORKFLOW_PUSH_METRICS]?.color,
                          })),
                  }
                : null,
        [appMetricsTrends]
    )

    return (
        <>
            <div className="flex flex-row gap-2 flex-wrap justify-center">
                {PUSH_METRIC_KEYS.map((key) => {
                    const metric = WORKFLOW_PUSH_METRICS[key]
                    return (
                        <AppMetricSummary
                            key={key}
                            name={metric.name}
                            description={metric.description}
                            loading={appMetricsTrendsLoading}
                            timeSeries={getSingleTrendSeries(key)}
                            previousPeriodTimeSeries={getSingleTrendSeries(key, true)}
                            color={metric.color}
                            colorIfZero={getColorVar('muted')}
                        />
                    )
                })}
            </div>
            <AppMetricsTrends appMetricsTrends={pushTrends} loading={appMetricsTrendsLoading} />
        </>
    )
}
