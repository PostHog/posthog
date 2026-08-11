import { useValues } from 'kea'
import { useMemo } from 'react'

import { getColorVar } from 'lib/colors'
import { AppMetricsTimeSeriesResponse, appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { percentage } from 'lib/utils/numbers'

import { WorkflowMetricCard } from './WorkflowMetricCard'
import {
    EMAIL_METRIC_INVOCATION_FILTERS,
    EmailMetric,
    METRIC_COLORS,
    WORKFLOW_EMAIL_METRICS,
} from './workflowMetricsSummaryLogic'

const EMAIL_METRIC_KEYS = Object.keys(WORKFLOW_EMAIL_METRICS) as (keyof typeof WORKFLOW_EMAIL_METRICS)[]

function sumTimeSeries(timeSeries: AppMetricsTimeSeriesResponse | null): number {
    if (!timeSeries) {
        return 0
    }
    return timeSeries.series.reduce((acc, curr) => acc + curr.values.reduce((acc, curr) => acc + curr, 0), 0)
}

export function EmailMetricsSummary({
    logicKey,
    onMetricClick,
}: {
    logicKey: string
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
                          })),
                  }
                : null,
        [appMetricsTrends]
    )

    const sentTotal = sumTimeSeries(getSingleTrendSeries('email_sent'))

    return (
        <>
            <div className="flex flex-row gap-2 flex-wrap justify-center">
                {EMAIL_METRIC_KEYS.map((key) => {
                    const metric = WORKFLOW_EMAIL_METRICS[key]
                    const canDrillDown = !!onMetricClick && !!EMAIL_METRIC_INVOCATION_FILTERS[key]
                    const shareOfSent =
                        key !== 'email_sent' && sentTotal > 0
                            ? percentage(sumTimeSeries(getSingleTrendSeries(key)) / sentTotal, 1)
                            : null
                    return (
                        <WorkflowMetricCard
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
                            footer={shareOfSent ? <span>{shareOfSent} of sent</span> : null}
                        />
                    )
                })}
            </div>
            <AppMetricsTrends
                appMetricsTrends={emailTrends}
                loading={appMetricsTrendsLoading}
                seriesColors={METRIC_COLORS}
            />
        </>
    )
}
