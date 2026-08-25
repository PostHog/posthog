import { LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { ScoutReportAction } from '../../../logics/scoutDetailLogic'
import { SignalReport } from '../../../types'
import { deriveHeadline, humanizeReportTitle } from '../../../utils/reportPresentation'
import { prettifyScoutSkillName } from '../../../utils/scoutRunsWindow'
import { SignalReportPriorityBadge } from '../../badges/SignalReportPriorityBadge'
import { SignalReportStatusBadge } from '../../badges/SignalReportStatusBadge'

export function ScoutReportCard({
    report,
    action,
    skillName,
}: {
    report: SignalReport
    action: ScoutReportAction
    /** Set on cross-fleet listings to show the touching scout's name (omitted on the per-scout page). */
    skillName?: string
}): JSX.Element {
    const cardTitle = humanizeReportTitle(report.title, 'Untitled report')
    const headline = deriveHeadline(report.summary)

    return (
        <Link
            to={urls.inboxReport('reports', report.id)}
            className="group flex w-full items-start gap-3 rounded border border-primary bg-surface-primary px-4 py-3.5 text-left no-underline transition-all duration-150 hover:border-secondary hover:bg-surface-secondary"
        >
            {report.priority && (
                <div className="shrink-0">
                    <SignalReportPriorityBadge priority={report.priority} />
                </div>
            )}
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="line-clamp-2 text-sm font-medium text-default">{cardTitle}</span>
                {headline && <span className="line-clamp-2 text-xs leading-snug text-secondary">{headline}</span>}
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-tertiary">
                    <LemonTag size="small" type={action === 'authored' ? 'success' : 'muted'}>
                        {action === 'authored' ? 'Authored' : 'Edited'}
                    </LemonTag>
                    <SignalReportStatusBadge status={report.status} />
                    {skillName && <span className="truncate">{prettifyScoutSkillName(skillName)}</span>}
                    <span className="flex-1" />
                    <TZLabel time={report.updated_at} />
                </div>
            </div>
        </Link>
    )
}
