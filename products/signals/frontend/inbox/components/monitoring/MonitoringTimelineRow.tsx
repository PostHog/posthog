/* eslint-disable react/forbid-dom-props -- positions along the time axis are data, not a design-scale value */
import clsx from 'clsx'

import { IconChevronRight } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type { SignalReportListApi } from 'products/signals/frontend/generated/api.schemas'

import {
    axisPercent,
    type MonitoringBarTone,
    monitoringBarTone,
    monitoringRowStatus,
    monitoringSpan,
} from '../../utils/monitoringTimeline'
import { displayConventionalCommitTitle } from '../../utils/reportPresentation'
import { MonitoringRowDetail } from './MonitoringRowDetail'

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

export function MonitoringTimelineRow({
    report,
    now,
    axisStart,
    axisEnd,
    expanded,
    onToggle,
}: {
    report: SignalReportListApi
    now: number
    axisStart: number
    axisEnd: number
    expanded: boolean
    onToggle: () => void
}): JSX.Element {
    const status = monitoringRowStatus(report, now)
    const span = monitoringSpan(report)
    const outcome = report.monitoring_outcome
    const left = span ? axisPercent(span.start, axisStart, axisEnd) : 0
    const right = span?.end != null ? axisPercent(span.end, axisStart, axisEnd) : null
    const readings = report.monitoring_summary?.lead_check?.readings ?? []
    // Covers the Now line where the row's labels sit, in the row's own background.
    const labelBackground = expanded ? 'bg-surface-secondary' : 'bg-surface-primary'

    return (
        <div
            className={clsx('-mx-3 border-b border-primary px-3 last:border-b-0', expanded && 'bg-surface-secondary')}
            data-attr="inbox-monitoring-row"
        >
            <button
                type="button"
                aria-expanded={expanded}
                onClick={onToggle}
                className="flex w-full cursor-pointer flex-wrap items-center gap-x-3 gap-y-1.5 py-3 text-left @2xl:flex-nowrap"
            >
                <div
                    className={clsx(
                        'relative z-10 flex min-w-0 flex-1 items-center gap-1.5 @2xl:w-80 @2xl:flex-none',
                        labelBackground
                    )}
                >
                    <IconChevronRight
                        className={clsx(
                            'size-4 shrink-0 text-tertiary transition-transform motion-reduce:transition-none',
                            expanded && 'rotate-90'
                        )}
                    />
                    <span className="min-w-0 flex-1 truncate text-sm font-semibold text-primary">
                        {displayConventionalCommitTitle(report.title, 'Untitled report')}
                    </span>
                </div>
                {/* Beside the title on a phone; its own column at the right edge once the bar has room. */}
                <div
                    className={clsx(
                        'relative z-10 flex shrink-0 justify-end @2xl:order-last @2xl:w-28',
                        labelBackground
                    )}
                >
                    <Tooltip title={status.description}>
                        <LemonTag size="small" type={status.type}>
                            {status.label}
                        </LemonTag>
                    </Tooltip>
                </div>
                <div className="relative h-5 basis-full @2xl:flex-1 @2xl:basis-auto">
                    {span && right != null ? (
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
                                    style={{
                                        left: `${axisPercent(Date.parse(reading.measured_at), axisStart, axisEnd)}%`,
                                    }}
                                />
                            ))}
                            <Tooltip
                                title={
                                    outcome
                                        ? `${status.label}, ${dayjs(outcome.ended_at).format('MMM D')}`
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
                    ) : null}
                </div>
            </button>
            {expanded ? (
                // Above the Now line, which runs the full height of the timeline.
                <div className="relative z-10 -mx-3 bg-surface-secondary px-3 pb-4">
                    <MonitoringRowDetail report={report} now={now} />
                </div>
            ) : null}
        </div>
    )
}
