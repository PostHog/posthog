import { hasOpenImplementationPr } from '@posthog/agent-contracts/signal-report-state'

import type { SignalReportPullRequestApi } from 'products/signals/frontend/generated/api.schemas'

import type { SignalReport } from '../types'

type ReportWithPullRequests = Pick<
    SignalReport,
    'pull_requests' | 'implementation_pr_url' | 'implementation_pr_state' | 'implementation_pr_merged'
>

export type ReportPullRequest = {
    id: string | null
    url: string
    state: 'unknown' | 'draft' | 'open' | 'closed' | 'merged'
    merged: boolean
    review_decision: SignalReportPullRequestApi['review_decision']
    merged_at: SignalReportPullRequestApi['merged_at']
}

export function reportPullRequests(report: ReportWithPullRequests | null | undefined): readonly ReportPullRequest[] {
    if (report?.pull_requests !== undefined) {
        return report.pull_requests
    }
    return report?.implementation_pr_url
        ? [
              {
                  id: null,
                  url: report.implementation_pr_url,
                  state: report.implementation_pr_state ?? (report.implementation_pr_merged ? 'merged' : 'unknown'),
                  merged: report.implementation_pr_merged ?? false,
                  review_decision: null,
                  merged_at: null,
              },
          ]
        : []
}

export function primaryReportPullRequest(report: ReportWithPullRequests | null | undefined): ReportPullRequest {
    const rank = (pr: ReportPullRequest): number => (pr.state === 'merged' ? 1 : pr.state === 'closed' ? 2 : 0)
    return (
        [...reportPullRequests(report)].sort(
            (a, b) => rank(a) - rank(b) || a.url.toLowerCase().localeCompare(b.url.toLowerCase())
        )[0] ?? { id: null, url: '', state: 'unknown', merged: false, review_decision: null, merged_at: null }
    )
}

export function hasActiveReportPullRequest(report: ReportWithPullRequests | null | undefined): boolean {
    return report != null && hasOpenImplementationPr(report)
}

export function hasMergedReportPullRequest(report: ReportWithPullRequests | null | undefined): boolean {
    return reportPullRequests(report).some((pr) => pr.merged || pr.state === 'merged')
}

export function hasApprovedOpenReportPullRequest(report: ReportWithPullRequests | null | undefined): boolean {
    return reportPullRequests(report).some(
        (pr) => pr.state === 'open' && !pr.merged && pr.review_decision === 'approved'
    )
}

const PR_MONITORING_HORIZON_MS = 90 * 24 * 60 * 60 * 1000

export function prMonitoringWindowExpiredReason(
    report: Pick<SignalReport, 'pull_requests'>,
    prUrl: string,
    nowMs = Date.now()
): string | undefined {
    const pr = (report.pull_requests ?? []).find((entry) => entry.url === prUrl)
    if (!pr || (!pr.merged && pr.state !== 'merged')) {
        return undefined
    }
    const mergedAtMs = pr.merged_at ? Date.parse(pr.merged_at) : Number.NaN
    return Number.isNaN(mergedAtMs) || mergedAtMs <= nowMs - PR_MONITORING_HORIZON_MS
        ? 'Pull requests merged more than 90 days ago are outside the monitoring window'
        : undefined
}
