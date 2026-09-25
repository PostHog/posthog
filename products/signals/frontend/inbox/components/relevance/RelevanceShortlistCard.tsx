import { LemonButton } from '@posthog/lemon-ui'

import { SignalReport } from '../../types'
import { inboxReportDetailUrl } from '../../utils/inboxReportUrls'
import { deriveHeadline } from '../../utils/reportPresentation'
import { hasActiveReportPullRequest } from '../../utils/reportPullRequests'
import { SignalReportPriorityBadge } from '../badges/SignalReportPriorityBadge'
import { ReportCardImpactMetric } from '../cards/ReportCardImpactMetric'

export function RelevanceShortlistCard({
    report,
    saving,
    onSnooze,
}: {
    report: SignalReport
    saving: boolean
    onSnooze: () => void
}): JSX.Element {
    const nextAction = hasActiveReportPullRequest(report)
        ? 'Review PR'
        : report.actionability === 'requires_human_input'
          ? 'Answer question'
          : 'Investigate'
    const reason = hasActiveReportPullRequest(report)
        ? 'A pull request is ready to review.'
        : report.actionability === 'requires_human_input'
          ? 'This report needs human input.'
          : 'This report is actionable and no one has claimed it.'
    return (
        <article className="rounded border border-primary p-4 space-y-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <h3 className="m-0 min-w-0 break-words flex-1">{report.title || 'Untitled report'}</h3>
                {report.priority && <SignalReportPriorityBadge priority={report.priority} />}
            </div>
            {deriveHeadline(report.summary) && <p className="line-clamp-2 mb-0">{deriveHeadline(report.summary)}</p>}
            <p className="text-secondary mb-0">{`You are a suggested reviewer. ${reason}`}</p>
            <ReportCardImpactMetric metrics={report.metrics} />
            <div className="flex flex-wrap gap-2">
                <LemonButton type="primary" to={inboxReportDetailUrl(report.id)} data-attr="inbox-shortlist-open">
                    {nextAction}
                </LemonButton>
                <LemonButton
                    type="secondary"
                    onClick={onSnooze}
                    loading={saving}
                    tooltip="Hide only from your shortlist for seven days"
                    data-attr="inbox-shortlist-not-now"
                >
                    Not now
                </LemonButton>
            </div>
        </article>
    )
}
