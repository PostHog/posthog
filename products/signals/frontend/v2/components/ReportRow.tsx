import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { DemoReport } from '../types'
import { v2InboxLogic } from '../v2InboxLogic'
import { SourceTag } from './SourceTag'

/** Reports without their own fix experiment still need a flag key for the demo modal. */
export function flagKeyFor(report: DemoReport): string {
    return report.content?.fix?.flagKey ?? report.focus?.flagKey ?? `fix_${report.id.toLowerCase().replace(/-/g, '_')}`
}

/** Resolved reports open the resolved page; everything else opens the full report. */
export function reportUrlFor(report: DemoReport): string {
    return report.status === 'Resolved' ? urls.v2Resolved(report.id) : urls.v2Report(report.id)
}

export function ReportRow({ report }: { report: DemoReport }): JSX.Element {
    const { expandedRowId } = useValues(v2InboxLogic)
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
                        report.live && 'bg-success',
                        !report.unread && !report.live && 'border border-primary'
                    )}
                />
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <Link to={reportUrl} subtle className="font-semibold" data-attr="v2-row-headline">
                        {report.headline}
                    </Link>
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-secondary">
                        <span className="font-mono lowercase">{report.area}</span>
                        {report.sources.map((source) => (
                            <SourceTag key={source} source={source} />
                        ))}
                        <span>created {report.created}</span>
                    </div>
                </div>
                <span className="flex-none font-mono font-semibold">{report.impact}</span>
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
                        {report.status === 'Verifying' && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                to={urls.v2Monitor(report.id)}
                                data-attr="v2-open-monitor"
                            >
                                View monitor
                            </LemonButton>
                        )}
                        {!isClosed && report.status !== 'Disputed' && (
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
