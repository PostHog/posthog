import { Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { DemoReport, InboxDemoGroup } from '../types'
import { reportUrlFor } from './ReportRow'

function SparklineBars({ values }: { values: number[] }): JSX.Element {
    const maxValue = Math.max(...values, 1)
    return (
        <div className="flex h-4.5 w-18 flex-none items-end gap-0.5" aria-hidden>
            {values.map((value, index) => (
                <div
                    key={index}
                    className={cn(
                        'min-h-0.5 flex-1 rounded-[1px]',
                        index === values.length - 1 ? 'bg-accent' : 'bg-border-primary'
                    )}
                    style={{ height: `${Math.max(10, (value / maxValue) * 100)}%` }}
                />
            ))}
        </div>
    )
}

/** Compact one-line row for the grouped inbox layout: headline, area, created date, trend, and impact. */
/** Monitoring rows open the live monitor; the other groups open the report or resolved page. */
function groupedRowUrl(report: DemoReport, group: InboxDemoGroup): string {
    return group === 'monitoring' ? urls.v2Monitor(report.id) : reportUrlFor(report)
}

export function GroupedReportRow({ report, group }: { report: DemoReport; group: InboxDemoGroup }): JSX.Element {
    const isClosed = report.status === 'Resolved' || report.status === 'Dismissed'

    return (
        <Link
            to={groupedRowUrl(report, group)}
            className={cn(
                'flex items-center gap-3 rounded border border-primary bg-surface-primary px-4 py-2 text-primary hover:bg-surface-secondary',
                isClosed && 'opacity-70'
            )}
            data-attr="v2-grouped-row"
        >
            <span
                className={cn(
                    'size-1.5 flex-none rounded-full',
                    report.unread ? 'bg-accent' : report.live ? 'bg-success' : 'bg-transparent'
                )}
            />
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="truncate font-semibold">{report.headline}</span>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-secondary">
                    <span className="font-mono lowercase">{report.area}</span>
                    <span>created {report.created}</span>
                </div>
            </div>
            <SparklineBars values={report.sparkline} />
            <span
                className="min-w-26 flex-none border-b border-dotted border-primary text-right font-mono text-sm font-semibold"
                title={report.proof}
            >
                {report.impact}
            </span>
        </Link>
    )
}
