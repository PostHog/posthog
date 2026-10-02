import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { EmailMetricsTotals, METRICS_TOTALS_PERIOD_DAYS, emailMetricsTotalsLogic } from './emailMetricsTotalsLogic'

const TOTAL_LABELS: Record<keyof EmailMetricsTotals, string> = {
    sent: 'Sent',
    delivered: 'Delivered',
    opened: 'Opened',
    clicked: 'Clicked',
    bounced: 'Bounced',
    markedAsSpam: 'Marked as spam',
}

export function EmailMetricsTotalsCard(): JSX.Element {
    const { metricsTotals, metricsTotalsLoading, metricsTotalsError } = useValues(emailMetricsTotalsLogic)
    const { loadMetricsTotals } = useActions(emailMetricsTotalsLogic)

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3" data-attr="audience-engagement-metrics-totals">
            <div className="flex flex-col gap-1">
                <h3 className="font-semibold m-0">Emails in the last {METRICS_TOTALS_PERIOD_DAYS} days</h3>
                <p className="text-secondary m-0">From workflow metrics, across every workflow and broadcast.</p>
            </div>
            {metricsTotalsLoading ? (
                <LemonSkeleton className="h-12" />
            ) : metricsTotalsError || !metricsTotals ? (
                <div className="flex flex-wrap items-center gap-2">
                    <p className="m-0">
                        Couldn't load workflow metrics{metricsTotalsError ? `: ${metricsTotalsError}` : '.'}
                    </p>
                    <LemonButton size="small" type="secondary" onClick={() => loadMetricsTotals()}>
                        Try again
                    </LemonButton>
                </div>
            ) : (
                <dl className="flex flex-wrap gap-x-8 gap-y-3 m-0">
                    {(Object.keys(TOTAL_LABELS) as (keyof EmailMetricsTotals)[]).map((key) => (
                        <div key={key} className="flex flex-col">
                            <dt className="text-secondary text-xs">{TOTAL_LABELS[key]}</dt>
                            <dd className="text-2xl font-semibold m-0">{humanFriendlyNumber(metricsTotals[key])}</dd>
                        </div>
                    ))}
                </dl>
            )}
        </LemonCard>
    )
}
