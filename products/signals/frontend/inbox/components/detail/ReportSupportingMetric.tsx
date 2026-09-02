import { TZLabel } from 'lib/components/TZLabel'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { formatReportMetricValue } from '../../utils/reportMetrics'

export interface ReportSupportingMetricLiveState {
    value: number | null
    loading: boolean
    error: boolean
}

export function ReportSupportingMetric({
    metric,
    liveState,
}: {
    metric: ReportMetricApi
    liveState?: ReportSupportingMetricLiveState
}): JSX.Element {
    const snapshot = formatReportMetricValue(metric, metric.value)
    const liveValue = liveState ? formatReportMetricValue(metric, liveState.value) : null
    const formattedValue = liveValue ?? snapshot
    const formattedComparison = metric.comparison ? formatReportMetricValue(metric, metric.comparison.value) : null
    const usingSnapshot = !liveValue && !!snapshot

    return (
        <LemonCard hoverEffect={false} className="flex h-full min-w-0 flex-col gap-1.5 p-3" data-attr="report-metric">
            <h3 className="m-0 truncate text-xs font-medium text-secondary" title={metric.title}>
                {metric.title}
            </h3>
            <div className="text-xl font-semibold leading-tight break-words tabular-nums text-primary">
                {formattedValue ?? 'Not available'}
            </div>
            {liveState?.loading ? (
                <p className="m-0 flex items-center gap-1 text-xs text-tertiary">
                    {!snapshot ? <Spinner className="text-sm" /> : null}
                    {snapshot ? 'Refreshing current value' : 'Loading current value'}
                </p>
            ) : liveState?.error ? (
                <p className="m-0 text-xs text-tertiary">
                    Couldn't refresh this metric.{usingSnapshot ? ' Showing the latest saved value.' : null} Refresh the
                    page to try again.
                </p>
            ) : liveState && liveValue ? (
                <span className="text-xs text-tertiary">Current window</span>
            ) : liveState ? (
                <p className="m-0 text-xs text-tertiary">
                    No current value.{usingSnapshot ? ' Showing the latest saved value.' : null}
                </p>
            ) : null}
            {(!liveState || usingSnapshot) && metric.comparison && formattedComparison ? (
                <p className="m-0 text-xs text-tertiary">
                    {metric.comparison.label}: {formattedComparison}
                </p>
            ) : null}
            {metric.value_at && (!liveState || usingSnapshot) ? (
                <span className="text-xs text-tertiary">
                    Measured <TZLabel time={metric.value_at} />
                </span>
            ) : null}
            {metric.caption ? <p className="m-0 break-words text-xs text-tertiary">{metric.caption}</p> : null}
        </LemonCard>
    )
}
