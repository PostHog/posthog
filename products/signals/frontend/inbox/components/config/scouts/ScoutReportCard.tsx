import { IconArrowRight } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { urls } from 'scenes/urls'

import { ScoutReportAction } from '../../../logics/scoutDetailLogic'
import { SignalReport } from '../../../types'
import { prettifyScoutSkillName } from '../../../utils/scoutRunsWindow'
import { SignalReportPriorityBadge } from '../../badges/SignalReportPriorityBadge'
import { SignalReportStatusBadge } from '../../badges/SignalReportStatusBadge'

/**
 * One report a scout touched through the report channel (`emit_report` / `edit_report`), in the
 * detail Reports section and the cross-fleet findings page. Unlike a finding's "In report" chip, the
 * run carries the report id directly, so this links straight to the inbox report — the whole card is
 * the link. An "Authored" vs "Edited" tag records how the scout touched it; priority/status come from
 * the live report. Cross-fleet listings pass `skillName` to surface which scout touched it.
 */
export function ScoutReportCard({
    report,
    action,
    skillName,
}: {
    report: SignalReport
    action: ScoutReportAction
    /** Set on cross-fleet listings to show the touching scout's name (omitted on the per-scout detail page). */
    skillName?: string
}): JSX.Element {
    return (
        <Link
            to={urls.inboxReport('reports', report.id)}
            className="flex flex-col gap-1 rounded border border-primary bg-bg-light px-3 py-2 hover:border-accent"
        >
            <div className="flex items-center gap-2">
                <LemonTag size="small" type={action === 'authored' ? 'success' : 'default'}>
                    {action === 'authored' ? 'Authored' : 'Edited'}
                </LemonTag>
                <SignalReportPriorityBadge priority={report.priority} />
                <SignalReportStatusBadge status={report.status} />
                {skillName && (
                    <span className="truncate text-xs font-medium text-default">
                        {prettifyScoutSkillName(skillName)}
                    </span>
                )}
                <span className="flex-1" />
                <span className="whitespace-nowrap text-[11px] text-muted">
                    {humanFriendlyDetailedTime(report.updated_at)}
                </span>
                <IconArrowRight className="size-3 shrink-0 text-muted" />
            </div>
            <span className="line-clamp-2 text-sm font-medium text-primary">{report.title || 'Untitled report'}</span>
        </Link>
    )
}
