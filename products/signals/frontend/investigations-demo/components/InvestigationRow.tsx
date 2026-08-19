import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { investigationsInboxLogic } from '../investigationsInboxLogic'
import { DemoInvestigation } from '../types'
import { InvestigationStateTag } from './InvestigationStateTag'

/** Investigations without their own fix experiment still need a flag key for the demo modal. */
export function flagKeyFor(investigation: DemoInvestigation): string {
    return investigation.focus?.flagKey ?? `fix_${investigation.id.toLowerCase().replace(/-/g, '_')}`
}

export function InvestigationRow({ investigation }: { investigation: DemoInvestigation }): JSX.Element {
    const { expandedRowId, liveActivityPhrase } = useValues(investigationsInboxLogic)
    const { toggleRowExpanded, openPrModal } = useActions(investigationsInboxLogic)

    const isExpanded = expandedRowId === investigation.id
    const isClosed = investigation.status === 'Resolved' || investigation.status === 'Dismissed'
    const reportUrl = investigation.hasReport ? urls.investigationsDemoReport(investigation.id) : null

    return (
        <div
            className={cn(
                'bg-surface-primary border border-primary rounded overflow-hidden',
                investigation.unread && 'border-l-2 border-l-accent',
                isClosed && 'opacity-70'
            )}
        >
            <div className="flex items-center gap-4 px-4 py-3">
                <span
                    className={cn(
                        'size-2 flex-none rounded-full',
                        investigation.unread && 'bg-accent',
                        investigation.live && 'bg-success animate-pulse motion-reduce:animate-none',
                        !investigation.unread && !investigation.live && 'border border-primary'
                    )}
                />
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <Link
                        to={reportUrl ?? undefined}
                        onClick={reportUrl ? undefined : () => toggleRowExpanded(investigation.id)}
                        subtle
                        className="font-semibold"
                        data-attr="investigations-demo-row-headline"
                    >
                        {investigation.headline}
                    </Link>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-secondary">
                        <span className="font-mono tracking-wide uppercase">{investigation.area}</span>
                        <span>created {investigation.created}</span>
                        {investigation.live && <span className="text-accent italic">{liveActivityPhrase}</span>}
                    </div>
                    {investigation.live && <LemonSkeleton className="h-1 max-w-96 motion-reduce:animate-none" />}
                </div>
                <div className="flex flex-none flex-col items-end gap-1">
                    <span className="font-mono font-semibold">{investigation.impact}</span>
                    <InvestigationStateTag state={investigation.state} live={investigation.live} />
                </div>
                <LemonButton
                    size="small"
                    icon={<IconChevronDown className={isExpanded ? 'rotate-180' : undefined} />}
                    onClick={() => toggleRowExpanded(investigation.id)}
                    tooltip={isExpanded ? 'Hide the preview' : 'Show the preview'}
                    data-attr="investigations-demo-row-peek"
                />
            </div>
            {isExpanded && (
                <div className="flex flex-wrap items-start gap-6 border-t border-primary bg-surface-secondary px-4 py-3 pl-10">
                    <div className="flex min-w-64 flex-1 flex-col gap-2">
                        <span className="font-mono text-[10px] tracking-widest text-tertiary uppercase">Preview</span>
                        <p className="mb-0 text-sm">{investigation.verdict}</p>
                        <span className="font-mono text-xs text-secondary">{investigation.proof}</span>
                    </div>
                    <div className="flex flex-none items-center gap-2">
                        {reportUrl && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                to={reportUrl}
                                data-attr="investigations-demo-open-report"
                            >
                                Open report
                            </LemonButton>
                        )}
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => openPrModal(flagKeyFor(investigation))}
                            data-attr="investigations-demo-fix-and-monitor"
                        >
                            Fix &amp; monitor
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}
