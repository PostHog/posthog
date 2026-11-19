import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { SignalReportListApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxReportDetailUrl } from '../../utils/inboxReportUrls'
import { parsePrUrlParts, safeHttpUrl } from '../../utils/reportPresentation'
import { primaryReportPullRequest } from '../../utils/reportPullRequests'
import { MonitoringCheckList } from './MonitoringCheckList'
import { MonitoringEvidence } from './MonitoringEvidence'
import { MonitoringOutcomeNote } from './MonitoringOutcomeNote'
import { MonitoringRowFacts } from './MonitoringRowFacts'

export function MonitoringRowDetail({ report, now }: { report: SignalReportListApi; now: number }): JSX.Element {
    const summary = report.monitoring_summary
    const prUrl = safeHttpUrl(primaryReportPullRequest(report).url)
    const prNumber = prUrl ? parsePrUrlParts(prUrl)?.number : null

    return (
        <div className="flex flex-col gap-3 rounded border border-primary bg-surface-primary p-4">
            <div className="flex flex-col gap-0.5">
                <div className="text-sm font-semibold">{report.title ?? 'Untitled report'}</div>
                {report.summary_lead ? <div className="text-sm text-secondary">{report.summary_lead}</div> : null}
            </div>
            <div className="flex flex-col gap-4 @2xl:flex-row">
                <div className="min-w-0 flex-1">
                    {report.monitoring_outcome ? (
                        <MonitoringOutcomeNote outcome={report.monitoring_outcome} />
                    ) : summary ? (
                        <MonitoringEvidence report={report} summary={summary} now={now} />
                    ) : (
                        <div className="rounded bg-surface-secondary p-3 text-sm text-secondary">
                            The follow-up checks run when this fix's window ends.
                        </div>
                    )}
                </div>
                <div className="flex flex-col gap-3 @2xl:w-72 @2xl:shrink-0">
                    <MonitoringRowFacts report={report} now={now} />
                    <MonitoringCheckList checks={summary?.checks ?? []} />
                </div>
            </div>
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    size="small"
                    type="primary"
                    to={inboxReportDetailUrl(report.id, urls.inbox('monitoring'))}
                    data-attr="inbox-monitoring-open-report"
                >
                    Open report
                </LemonButton>
                {prUrl ? (
                    <LemonButton
                        size="small"
                        type="secondary"
                        to={prUrl}
                        targetBlank
                        data-attr="inbox-monitoring-open-pr"
                    >
                        {prNumber ? `PR #${prNumber}` : 'Pull request'}
                    </LemonButton>
                ) : null}
            </div>
        </div>
    )
}
