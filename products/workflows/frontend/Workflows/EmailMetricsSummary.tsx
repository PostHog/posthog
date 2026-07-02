import { useValues } from 'kea'
import { useMemo } from 'react'

import { getColorVar } from 'lib/colors'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'

import { EMAIL_METRIC_LOG_FILTERS, EmailMetric, WORKFLOW_EMAIL_METRICS } from './workflowMetricsSummaryLogic'

const EMAIL_METRIC_KEYS = Object.keys(WORKFLOW_EMAIL_METRICS) as (keyof typeof WORKFLOW_EMAIL_METRICS)[]

export function EmailMetricsSummary({
    logicKey,
    onMetricClick,
}: {
    logicKey: string
    /** Invoked when a drill-down-able metric tile (e.g. Bounced) is clicked. */
    onMetricClick?: (metricKey: EmailMetric) => void
}): JSX.Element {
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

    return (
        <>
            <div className="flex flex-row gap-2 flex-wrap justify-center">
                {EMAIL_METRIC_KEYS.map((key) => {
                    const metric = WORKFLOW_EMAIL_METRICS[key]
                    const canDrillDown = !!onMetricClick && !!EMAIL_METRIC_LOG_FILTERS[key]
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
                            onClick={canDrillDown ? () => onMetricClick(key) : undefined}
                            onClickTooltip={`View invocations with a ${metric.name.toLowerCase()} log entry in this timeframe`}
                        />
                    )
                })}
            </div>
            <AppMetricsTrends appMetricsTrends={emailTrends} loading={appMetricsTrendsLoading} />
        </>
    )
}
