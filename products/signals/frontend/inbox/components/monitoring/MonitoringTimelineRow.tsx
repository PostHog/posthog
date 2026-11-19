import clsx from 'clsx'

import { IconChevronRight } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import type { SignalReportListApi } from 'products/signals/frontend/generated/api.schemas'

import { monitoringRowStatus } from '../../utils/monitoringTimeline'
import { displayConventionalCommitTitle } from '../../utils/reportPresentation'
import { MonitoringRowDetail } from './MonitoringRowDetail'
import { MonitoringTimelineBar } from './MonitoringTimelineBar'

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
                    <MonitoringTimelineBar
                        report={report}
                        now={now}
                        axisStart={axisStart}
                        axisEnd={axisEnd}
                        statusLabel={status.label}
                    />
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
