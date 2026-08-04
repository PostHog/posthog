import { useValues } from 'kea'
import { useMemo } from 'react'

import { getColorVar } from 'lib/colors'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { AppMetricSummary, sumAppMetricsTimeSeries } from 'lib/components/AppMetrics/AppMetricSummary'
import { percentage } from 'lib/utils/numbers'

import { WORKFLOW_EMAIL_METRICS } from './workflowMetricsSummaryLogic'

const EMAIL_METRIC_KEYS = Object.keys(WORKFLOW_EMAIL_METRICS) as (keyof typeof WORKFLOW_EMAIL_METRICS)[]

export function EmailMetricsSummary({ logicKey }: { logicKey: string }): JSX.Element {
    const { appMetricsTrendsLoading, appMetricsTrends, getSingleTrendSeries } = useValues(appMetricsLogic({ logicKey }))

    const emailTrends = useMemo(
        () =>
            appMetricsTrends
                ? {
                      ...appMetricsTrends,
                      series: appMetricsTrends.series
                          .filter((series) => series.name in WORKFLOW_EMAIL_METRICS)
                          .map((series) => ({
                              ...series,
                              name:
                                  WORKFLOW_EMAIL_METRICS[series.name as keyof typeof WORKFLOW_EMAIL_METRICS]?.name ??
                                  series.name,
                              color: WORKFLOW_EMAIL_METRICS[series.name as keyof typeof WORKFLOW_EMAIL_METRICS]?.color,
                          })),
                  }
                : null,
        [appMetricsTrends]
    )

    const sentTotal = sumAppMetricsTimeSeries(getSingleTrendSeries('email_sent'))

    return (
        <>
            <div className="flex flex-row gap-2 flex-wrap justify-center">
                {EMAIL_METRIC_KEYS.map((key) => {
                    const metric = WORKFLOW_EMAIL_METRICS[key]
                    const timeSeries = getSingleTrendSeries(key)
                    return (
                        <AppMetricSummary
                            key={key}
                            name={metric.name}
                            description={metric.description}
                            loading={appMetricsTrendsLoading}
                            timeSeries={timeSeries}
                            previousPeriodTimeSeries={getSingleTrendSeries(key, true)}
                            color={metric.color}
                            colorIfZero={getColorVar('muted')}
                            subtitle={
                                key !== 'email_sent' && sentTotal > 0
                                    ? `${percentage(sumAppMetricsTimeSeries(timeSeries) / sentTotal, 1)} of sent`
                                    : null
                            }
                        />
                    )
                })}
            </div>
            <AppMetricsTrends appMetricsTrends={emailTrends} loading={appMetricsTrendsLoading} />
        </>
    )
}
