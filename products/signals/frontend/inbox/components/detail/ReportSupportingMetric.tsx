import { TZLabel } from 'lib/components/TZLabel'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import {
    formatReportMetricParts,
    formatReportMetricValue,
    reportMetricDelta,
    reportMetricWindowLabel,
} from '../../utils/reportMetrics'
import { ReportMetricDeltaBadge } from './ReportMetricDeltaBadge'

export interface ReportSupportingMetricLiveState {
    value: number | null
    loading: boolean
    error: boolean
}

/** One tile in the Impact grid: the figure first, then what it counts and any saved-value context. */
export function ReportSupportingMetric({
    metric,
    liveState,
}: {
    metric: ReportMetricApi
    liveState?: ReportSupportingMetricLiveState
}): JSX.Element {
    const liveParts = liveState ? formatReportMetricParts(metric, liveState.value) : null
    const snapshotParts = formatReportMetricParts(metric, metric.value)
    const parts = liveParts ?? snapshotParts
    const shownValue = liveParts ? liveState?.value : metric.value
    const formattedComparison = metric.comparison ? formatReportMetricValue(metric, metric.comparison.value) : null
    const usingSnapshot = !liveParts && !!snapshotParts
    const windowLabel = reportMetricWindowLabel(metric.query) ?? 'Current window'
    const delta = metric.comparison ? reportMetricDelta(metric, shownValue, metric.comparison.value) : null

    return (
        <LemonCard
            hoverEffect={false}
            className="flex h-full min-w-0 flex-col gap-1 bg-surface-secondary p-3.5"
            data-attr="report-metric"
        >
            <div className="font-mono text-xl font-semibold leading-tight break-words tabular-nums text-primary">
                {parts ? (
                    <>
                        {parts.value}
                        {parts.unit ? (
                            <>
                                {' '}
                                <span className="text-xs font-normal text-secondary">{parts.unit}</span>
                            </>
                        ) : null}
                    </>
                ) : (
                    'Not available'
                )}
            </div>
            <h3 className="m-0 text-[11px] font-normal leading-normal tracking-wide break-words text-secondary">
                {metric.title}
            </h3>
            {liveState?.loading ? (
                <p className="m-0 flex items-center gap-1 text-[11px] text-tertiary">
                    {!snapshotParts ? <Spinner className="text-sm" /> : null}
                    {snapshotParts ? 'Refreshing current value' : 'Loading current value'}
                </p>
            ) : liveState?.error ? (
                <p className="m-0 text-[11px] text-tertiary">
                    Couldn't refresh this metric.{usingSnapshot ? ' Showing the latest saved value.' : null} Refresh the
                    page to try again.
                </p>
            ) : liveState && liveParts ? (
                <span className="font-mono text-[11px] text-tertiary">{windowLabel}</span>
            ) : liveState ? (
                <p className="m-0 text-[11px] text-tertiary">
                    No current value.{usingSnapshot ? ' Showing the latest saved value.' : null}
                </p>
            ) : null}
            {parts && metric.comparison && formattedComparison ? (
                <p className="m-0 font-mono text-[11px] break-words text-tertiary">
                    {delta ? (
                        <>
                            <ReportMetricDeltaBadge delta={delta} />
                            <span aria-hidden> · </span>
                        </>
                    ) : null}
                    {metric.comparison.label}: {formattedComparison}
                </p>
            ) : null}
            {metric.value_at && (!liveState || usingSnapshot) ? (
                <span className="font-mono text-[11px] text-tertiary">
                    Measured <TZLabel time={metric.value_at} />
                </span>
            ) : null}
            {metric.caption ? <p className="m-0 break-words text-[11px] text-tertiary">{metric.caption}</p> : null}
        </LemonCard>
    )
}
