/* eslint-disable react/forbid-dom-props -- positions along the time axis are data, not a design-scale value */
import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { dayjs } from 'lib/dayjs'

import type { SignalReportListApi } from 'products/signals/frontend/generated/api.schemas'

import { monitoringTabLogic } from '../../logics/monitoringTabLogic'
import { axisPercent, monitoringAxis } from '../../utils/monitoringTimeline'
import { MonitoringTimelineRow } from './MonitoringTimelineRow'

const DAY_MS = 86_400_000

function LegendItem({ shape, children }: { shape: string; children: React.ReactNode }): JSX.Element {
    return (
        <span className="flex items-center gap-1">
            <span className={clsx('size-2 border border-primary', shape)} />
            {children}
        </span>
    )
}

// The date row and the Now line are offset by the title (20rem) and state (7rem) columns, so they line up with the bars.
export function MonitoringTimeline({ reports, now }: { reports: SignalReportListApi[]; now: number }): JSX.Element {
    const { expandedReportIds } = useValues(monitoringTabLogic)
    const { toggleExpanded } = useActions(monitoringTabLogic)
    const { start: axisStart, end: axisEnd } = monitoringAxis(reports, now)
    const days = Math.round((axisEnd - axisStart) / DAY_MS)
    const step = Math.max(1, Math.ceil(days / 12))
    const nearNow = (time: number): boolean => Math.abs(time - now) < DAY_MS
    const ticks = Array.from({ length: Math.ceil(days / step) }, (_, i) =>
        dayjs(axisStart)
            .startOf('day')
            .add((i + 1) * step, 'day')
            .valueOf()
    ).filter((tick) => tick < axisEnd - DAY_MS / 2)

    return (
        <div className="flex flex-col gap-1">
            {/* The transparent border and padding match the box below, so the dates line up with the bars. */}
            <div className="border-x border-transparent px-3">
                <div className="flex text-[11px] text-tertiary @2xl:pl-[20.75rem] @2xl:pr-[7.75rem]">
                    <div className="relative h-4 flex-1">
                        {ticks.map((tick, index) => (
                            <span
                                key={tick}
                                className={clsx(
                                    'absolute -translate-x-1/2 whitespace-nowrap tabular-nums',
                                    nearNow(tick) ? 'hidden' : index % 2 === 1 && 'hidden @5xl:inline'
                                )}
                                style={{ left: `${axisPercent(tick, axisStart, axisEnd)}%` }}
                            >
                                {dayjs(tick).format('MMM D')}
                            </span>
                        ))}
                        <span
                            className="absolute -translate-x-1/2 font-semibold text-primary"
                            style={{ left: `${axisPercent(now, axisStart, axisEnd)}%` }}
                        >
                            Now
                        </span>
                    </div>
                </div>
            </div>
            <div className="relative overflow-hidden rounded border border-primary bg-surface-primary px-3">
                <div className="pointer-events-none absolute inset-y-0 left-3 right-3 @2xl:left-[21.5rem] @2xl:right-[8.5rem]">
                    <div
                        className="absolute inset-y-0 w-px bg-border-bold"
                        style={{ left: `${axisPercent(now, axisStart, axisEnd)}%` }}
                    />
                </div>
                {reports.map((report) => (
                    <MonitoringTimelineRow
                        key={report.id}
                        report={report}
                        now={now}
                        axisStart={axisStart}
                        axisEnd={axisEnd}
                        expanded={expandedReportIds.includes(report.id)}
                        onToggle={() => toggleExpanded(report.id)}
                    />
                ))}
            </div>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-tertiary">
                <LegendItem shape="rounded-full bg-surface-primary">Interim reading</LegendItem>
                <LegendItem shape="rotate-45 bg-surface-primary">Verdict</LegendItem>
                <LegendItem shape="rotate-45 bg-success">Resolved</LegendItem>
                <LegendItem shape="rotate-45 bg-warning">Follow-up opened</LegendItem>
            </div>
        </div>
    )
}
