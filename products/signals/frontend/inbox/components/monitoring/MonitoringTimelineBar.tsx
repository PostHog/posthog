/* eslint-disable react/forbid-dom-props -- positions along the time axis are data, not a design-scale value */
import clsx from 'clsx'

import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type { SignalReportListApi } from 'products/signals/frontend/generated/api.schemas'

import { axisPercent, type MonitoringBarTone, monitoringBarTone, monitoringSpan } from '../../utils/monitoringTimeline'

const BAR_TONE: Record<MonitoringBarTone, string> = {
    success: 'bg-success',
    warning: 'bg-warning',
    strong: 'bg-border-bold',
    faint: 'bg-border-bold opacity-50',
}

const OUTCOME_MARK: Record<string, string> = {
    resolved: 'bg-success',
    resolved_by_assessment: 'bg-success',
    resolved_manually: 'bg-border-bold',
    closed: 'bg-warning',
}

/** The bar from when Monitoring started to its verdict, with interim readings and a verdict marker. */
export function MonitoringTimelineBar({
    report,
    now,
    axisStart,
    axisEnd,
    statusLabel,
}: {
    report: SignalReportListApi
    now: number
    axisStart: number
    axisEnd: number
    statusLabel: string
}): JSX.Element | null {
    const span = monitoringSpan(report)
    if (!span || span.end == null) {
        return null
    }
    const outcome = report.monitoring_outcome
    const left = axisPercent(span.start, axisStart, axisEnd)
    const right = axisPercent(span.end, axisStart, axisEnd)
    const readings = report.monitoring_summary?.lead_check?.readings ?? []
    return (
        <>
            <div
                className={clsx(
                    'absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full',
                    BAR_TONE[monitoringBarTone(report, now)],
                    span.start < axisStart && 'rounded-l-none'
                )}
                style={{ left: `${left}%`, width: `${Math.max(right - left, 0.8)}%` }}
            />
            {readings.map((reading) => (
                <span
                    key={reading.measured_at}
                    className={clsx(
                        'absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-primary',
                        reading.matches === false ? 'bg-warning' : 'bg-surface-primary'
                    )}
                    style={{ left: `${axisPercent(Date.parse(reading.measured_at), axisStart, axisEnd)}%` }}
                />
            ))}
            <Tooltip
                title={
                    outcome
                        ? `${statusLabel}, ${dayjs(outcome.ended_at).format('MMM D')}`
                        : `Verdict due ${dayjs(span.end).format('MMM D, h:mm A')}`
                }
            >
                <span
                    className={clsx(
                        'absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rotate-45 border border-primary',
                        outcome ? OUTCOME_MARK[outcome.kind] : 'bg-surface-primary'
                    )}
                    style={{ left: `${right}%` }}
                />
            </Tooltip>
        </>
    )
}
