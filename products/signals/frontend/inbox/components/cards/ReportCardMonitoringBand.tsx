import { IconEye } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import type { ReportMonitoringSummaryApi } from 'products/signals/frontend/generated/api.schemas'

import type { SignalReport } from '../../types'
import {
    latestMergedPullRequest,
    monitoringPullRequestStatus,
    monitoringTimeLeft,
    monitoringWindowProgress,
} from '../../utils/reportMonitoringSummary'
import { parsePrUrlParts, safeHttpUrl } from '../../utils/reportPresentation'
import { primaryReportPullRequest, reportPullRequests } from '../../utils/reportPullRequests'

/** The strip across the top of a Monitoring row: what was merged and when, and how far through the window it is. */
export function ReportCardMonitoringBand({
    report,
    summary,
    now,
    preview = false,
}: {
    report: SignalReport
    summary: ReportMonitoringSummaryApi | null
    now: number
    /** Onboarding sample: the PR url is fabricated, so it renders as text. */
    preview?: boolean
}): JSX.Element {
    const pullRequest = latestMergedPullRequest(reportPullRequests(report)) ?? primaryReportPullRequest(report)
    const prUrl = safeHttpUrl(pullRequest.url)
    const prNumber = prUrl ? parsePrUrlParts(prUrl)?.number : null
    const prStatus = monitoringPullRequestStatus(pullRequest, report.monitoring_started_at)
    const progress = summary ? monitoringWindowProgress(summary, now) : null

    return (
        <div
            className="flex flex-wrap items-center gap-x-2 gap-y-0.5 border-b border-primary bg-surface-secondary px-4 py-1.5 text-xs"
            data-attr="report-card-monitoring-band"
        >
            <IconEye className="size-4 shrink-0 text-success" />
            <span className="font-semibold">Monitoring</span>
            {prNumber ? (
                <span className="text-secondary">
                    PR{' '}
                    {prUrl && !preview ? (
                        <Link to={prUrl} target="_blank" data-attr="report-card-monitoring-pr-link">
                            #{prNumber}
                        </Link>
                    ) : (
                        `#${prNumber}`
                    )}
                    {prStatus ? ` ${prStatus}` : null}
                </span>
            ) : null}
            {summary ? (
                <span className="ml-auto text-tertiary tabular-nums">
                    {[progress, monitoringTimeLeft(summary.ends_at, now)].filter(Boolean).join(' · ')}
                </span>
            ) : null}
        </div>
    )
}
