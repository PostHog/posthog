import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonLabel } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'

import {
    DELIVERY_FEEDBACK_METRICS,
    EMAIL_METRIC_INVOCATION_FILTERS,
    EmailMetric,
    WORKFLOW_EMAIL_METRICS,
} from './workflowMetricsSummaryLogic'

const EMAIL_METRIC_KEYS = Object.keys(WORKFLOW_EMAIL_METRICS) as (keyof typeof WORKFLOW_EMAIL_METRICS)[]

// A custom SMTP relay confirms acceptance only, so "Sent" must not read as delivery.
const SMTP_SENT_OVERRIDE = {
    name: 'Sent / accepted by relay',
    description:
        "Total number of emails accepted by the sender's SMTP relay. Acceptance means the relay took responsibility for the message — it does not confirm delivery to the recipient's inbox.",
}

export function EmailMetricsSummary({
    logicKey,
    onMetricClick,
    smtpProvider = false,
}: {
    logicKey: string
    onMetricClick?: (metricKey: EmailMetric) => void
    /** True when this email action sends through a custom SMTP relay, which has no delivery feedback. */
    smtpProvider?: boolean
}): JSX.Element {
    const { appMetricsTrendsLoading, appMetricsTrends, getSingleTrendSeries } = useValues(appMetricsLogic({ logicKey }))

    const emailTrends = useMemo(
        () =>
            appMetricsTrends
                ? {
                      ...appMetricsTrends,
                      series: appMetricsTrends.series
                          .filter(
                              (series) =>
                                  series.name in WORKFLOW_EMAIL_METRICS &&
                                  // Delivery-feedback series are permanently flat for SMTP — leave
                                  // them off the chart rather than implying they are being measured.
                                  !(smtpProvider && DELIVERY_FEEDBACK_METRICS.includes(series.name as EmailMetric))
                          )
                          .map((series) => ({
                              ...series,
                              name:
                                  WORKFLOW_EMAIL_METRICS[series.name as keyof typeof WORKFLOW_EMAIL_METRICS]?.name ??
                                  series.name,
                              color: WORKFLOW_EMAIL_METRICS[series.name as keyof typeof WORKFLOW_EMAIL_METRICS]?.color,
                          })),
                  }
                : null,
        [appMetricsTrends, smtpProvider]
    )

    return (
        <>
            <div className="flex flex-row gap-2 flex-wrap justify-center">
                {EMAIL_METRIC_KEYS.map((key) => {
                    const metric = WORKFLOW_EMAIL_METRICS[key]
                    if (smtpProvider && DELIVERY_FEEDBACK_METRICS.includes(key)) {
                        return (
                            <div
                                key={key}
                                className="flex flex-1 flex-col relative border rounded p-3 bg-surface-primary min-w-[16rem]"
                            >
                                <LemonLabel
                                    info={`${metric.description} Custom SMTP relays report acceptance only, so this metric is not available for this sender.`}
                                >
                                    {metric.name}
                                </LemonLabel>
                                <div className="flex flex-1 items-center justify-center">
                                    <span className="text-muted text-md mb-2">Not supported by this provider</span>
                                </div>
                            </div>
                        )
                    }
                    const isSmtpSent = smtpProvider && key === 'email_sent'
                    const canDrillDown = !!onMetricClick && !!EMAIL_METRIC_INVOCATION_FILTERS[key]
                    return (
                        <AppMetricSummary
                            key={key}
                            name={isSmtpSent ? SMTP_SENT_OVERRIDE.name : metric.name}
                            description={isSmtpSent ? SMTP_SENT_OVERRIDE.description : metric.description}
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
