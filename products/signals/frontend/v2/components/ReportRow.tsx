import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { DemoReport } from '../types'
import { v2InboxLogic } from '../v2InboxLogic'
import { ReportStateTag } from './ReportStateTag'

/** Reports without their own fix experiment still need a flag key for the demo modal. */
export function flagKeyFor(report: DemoReport): string {
    return report.content?.fix?.flagKey ?? report.focus?.flagKey ?? `fix_${report.id.toLowerCase().replace(/-/g, '_')}`
}

/** Resolved reports open the resolved page; everything else opens the full report. */
export function reportUrlFor(report: DemoReport): string {
    return report.state === 'resolved' ? urls.v2Resolved(report.id) : urls.v2Report(report.id)
}

export function ReportRow({ report }: { report: DemoReport }): JSX.Element {
    const { expandedRowId, liveActivityPhrase } = useValues(v2InboxLogic)
    const { toggleRowExpanded, openPrModal } = useActions(v2InboxLogic)

    const isExpanded = expandedRowId === report.id
    const isClosed = report.status === 'Resolved' || report.status === 'Dismissed'
    const reportUrl = reportUrlFor(report)

    return (
        <div
            className={cn(
                'bg-surface-primary border border-primary rounded overflow-hidden',
                report.unread && 'border-l-2 border-l-accent',
                isClosed && 'opacity-70'
            )}
        >
            <div className="flex items-center gap-4 px-4 py-3">
                <span
                    className={cn(
                        'size-2 flex-none rounded-full',
                        report.unread && 'bg-accent',
                        report.live && 'bg-success animate-pulse motion-reduce:animate-none',
                        !report.unread && !report.live && 'border border-primary'
                    )}
                />
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <Link to={reportUrl} subtle className="font-semibold" data-attr="v2-row-headline">
                        {report.headline}
                    </Link>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-secondary">
                        <span className="font-mono tracking-wide uppercase">{report.area}</span>
                        <span>created {report.created}</span>
                        {report.live && <span className="text-accent italic">{liveActivityPhrase}</span>}
                    </div>
                    {report.live && <LemonSkeleton className="h-1 max-w-96 motion-reduce:animate-none" />}
                </div>
                <div className="flex flex-none flex-col items-end gap-1">
                    <span className="font-mono font-semibold">{report.impact}</span>
                    <ReportStateTag state={report.state} live={report.live} />
                </div>
                <LemonButton
                    size="small"
                    icon={<IconChevronDown className={isExpanded ? 'rotate-180' : undefined} />}
                    onClick={() => toggleRowExpanded(report.id)}
                    tooltip={isExpanded ? 'Hide the preview' : 'Show the preview'}
                    data-attr="v2-row-peek"
                />
            </div>
            {isExpanded && (
                <div className="flex flex-wrap items-start gap-6 border-t border-primary bg-surface-secondary px-4 py-3 pl-10">
                    <div className="flex min-w-64 flex-1 flex-col gap-2">
                        <span className="font-mono text-[10px] tracking-widest text-tertiary uppercase">Preview</span>
                        <p className="mb-0 text-sm">{report.verdict}</p>
                        <span className="font-mono text-xs text-secondary">{report.proof}</span>
                    </div>
                    <div className="flex flex-none items-center gap-2">
                        <LemonButton type="secondary" size="small" to={reportUrl} data-attr="v2-open-report">
                            Open report
                        </LemonButton>
                        {report.state === 'recovering' && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                to={urls.v2Monitor(report.id)}
                                data-attr="v2-open-monitor"
                            >
                                View monitor
                            </LemonButton>
                        )}
                        {!isClosed && report.state !== 'disputed' && (
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={() => openPrModal({ reportId: report.id, flagKey: flagKeyFor(report) })}
                                data-attr="v2-fix-and-monitor"
                            >
                                Fix &amp; monitor
                            </LemonButton>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}
