import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { derivePrState } from 'lib/signals/prState'
import { PrBadge } from 'lib/signals/SignalReportPrBadge'

import { useReportCiStatus } from '../../logics/prCiStatusLogic'
import { SignalReport } from '../../types'
import { reportMetricRowParts, selectReportCardImpactMetric } from '../../utils/reportMetrics'
import { parsePrUrlParts, safeHttpUrl } from '../../utils/reportPresentation'
import { primaryReportPullRequest } from '../../utils/reportPullRequests'
import { ReportClaimAvatar } from '../badges/ReportClaimAvatar'
import { useReportClaim } from '../badges/useReportClaim'

function Fact({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-1">
            <dt className="text-xxs font-semibold uppercase tracking-wide text-tertiary">{label}</dt>
            <dd className="m-0 flex min-w-0 items-center gap-1.5 text-sm text-primary">{children}</dd>
        </div>
    )
}

/**
 * The facts a triage decision needs, so the reader does not have to open the report: how big the problem
 * is, how much evidence backs it, whether a pull request exists, and who works on it.
 */
export function TriageReportFacts({ report }: { report: SignalReport }): JSX.Element {
    // Live impact figures roll out per team with the same flag as the list rows.
    const showImpact = useFeatureFlag('SIGNALS_REPORT_METRICS')
    const metric = showImpact ? selectReportCardImpactMetric(report.metrics) : null
    const metricParts = metric ? reportMetricRowParts(metric, metric.value) : null

    const pullRequest = primaryReportPullRequest(report)
    const prUrl = safeHttpUrl(pullRequest.url)
    const prNumber = prUrl ? (parsePrUrlParts(prUrl)?.number ?? null) : null
    const ciStatus = useReportCiStatus(prNumber ? report.id : null)

    const claim = useReportClaim(report.assignee)

    return (
        <dl
            className="m-0 grid grid-cols-2 gap-x-4 gap-y-3 @xl/triage:grid-cols-4"
            data-attr="inbox-triage-report-facts"
        >
            {metric && metricParts ? (
                <Fact label="Impact">
                    <span className="truncate" title={metric.title}>
                        <span className="font-semibold tabular-nums">{metricParts.value}</span>
                        {metricParts.unit ? <span className="text-secondary"> {metricParts.unit}</span> : null}
                    </span>
                </Fact>
            ) : null}
            <Fact label="Evidence">
                <span className="tabular-nums">
                    {report.signal_count} signal{report.signal_count === 1 ? '' : 's'}
                </span>
            </Fact>
            <Fact label="Pull request">
                {prNumber ? (
                    <PrBadge
                        prNumber={prNumber}
                        prUrl={prUrl}
                        state={derivePrState(report.status, pullRequest.merged === true, pullRequest.state)}
                        ciStatus={ciStatus}
                    />
                ) : report.implementation_in_flight ? (
                    <span className="text-secondary">Run in progress</span>
                ) : (
                    <span className="text-tertiary">None yet</span>
                )}
            </Fact>
            <Fact label="Assignee">
                {claim ? (
                    <>
                        <ReportClaimAvatar claim={claim} />
                        <span className="truncate">{claim.isMine ? 'You' : claim.name}</span>
                    </>
                ) : (
                    <span className="text-tertiary">Nobody yet</span>
                )}
            </Fact>
        </dl>
    )
}
