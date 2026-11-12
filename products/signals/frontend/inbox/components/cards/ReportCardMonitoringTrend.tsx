/* eslint-disable react/forbid-dom-props -- bar heights and line positions are data, not a design-scale value */
import clsx from 'clsx'

import type { MonitoringSummaryStateEnumApi } from 'products/signals/frontend/generated/api.schemas'

import type { MonitoringTrend } from '../../utils/reportMonitoringSummary'

const SINCE_FIX_BAR: Partial<Record<MonitoringSummaryStateEnumApi, string>> = {
    not_on_track: 'bg-warning',
    on_track: 'bg-success',
}

/**
 * The report metric's trailing buckets with the fix marked: bars before it recede, bars since take
 * the Monitoring state's colour, and a dashed line marks the target for one bucket when there is one.
 * Plain elements at a fixed height, like the row sparkline, so a list of rows mounts no charts.
 */
export function ReportCardMonitoringTrend({
    trend,
    state,
}: {
    trend: MonitoringTrend
    state: MonitoringSummaryStateEnumApi
}): JSX.Element {
    const { values, fixIndex, target } = trend
    const max = Math.max(...values, target ?? 0) * 1.1 || 1
    return (
        <div
            className="relative flex h-10 w-full items-end gap-px"
            aria-hidden
            data-attr="report-card-monitoring-trend"
        >
            {values.map((value, index) => (
                <div
                    key={index}
                    className={clsx(
                        'min-h-px flex-1 rounded-[1px]',
                        index >= fixIndex ? (SINCE_FIX_BAR[state] ?? 'bg-border-bold') : 'bg-border-primary',
                        // The last bucket is still filling.
                        index === values.length - 1 && 'opacity-60'
                    )}
                    style={{ height: `${Math.max(4, (value / max) * 100)}%` }}
                />
            ))}
            <div
                className="absolute -inset-y-0.5 w-px bg-border-bold"
                style={{ left: `${(fixIndex / values.length) * 100}%` }}
            />
            {target != null && (
                <div
                    className="absolute inset-x-0 border-t border-dashed border-border-bold"
                    style={{ bottom: `${(target / max) * 100}%` }}
                />
            )}
        </div>
    )
}
