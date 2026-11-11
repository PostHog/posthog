import clsx from 'clsx'

import { TZLabel } from 'lib/components/TZLabel'

import { SignalReport } from '../../types'

const DAY_MS = 24 * 60 * 60 * 1000

/** When the report opened, and when it last changed if that was on a later day. The sorted-by time comes first. */
export function ReportCardTimes({
    report,
    sortField,
    stacked,
}: {
    report: Pick<SignalReport, 'created_at' | 'updated_at'>
    sortField: 'created_at' | 'updated_at'
    stacked: boolean
}): JSX.Element {
    const updatedAt = report.updated_at ?? report.created_at
    const showsUpdate = new Date(updatedAt).getTime() - new Date(report.created_at).getTime() > DAY_MS
    const created = (
        <span key="created" className="flex items-center gap-1 whitespace-nowrap">
            <span>Opened</span>
            <TZLabel time={report.created_at} className="tabular-nums" title="Created" />
        </span>
    )
    const updated = showsUpdate ? (
        <span key="updated" className="flex items-center gap-1 whitespace-nowrap">
            <span>Updated</span>
            <TZLabel time={updatedAt} className="tabular-nums" title="Last updated" />
        </span>
    ) : null
    const times = sortField === 'updated_at' && updated ? [updated, created] : [created, updated]

    return (
        <span
            className={clsx(
                'flex shrink-0 text-xs leading-none text-tertiary',
                stacked ? 'flex-col items-end gap-1' : 'flex-wrap items-center gap-x-2 gap-y-1'
            )}
            data-attr="report-card-times"
        >
            {times}
        </span>
    )
}
