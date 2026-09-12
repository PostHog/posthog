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
              },
          ]
        : []
}

export function primaryReportPullRequest(report: ReportWithPullRequests | null | undefined): ReportPullRequest {
    const rank = (pr: ReportPullRequest): number => (pr.state === 'merged' ? 1 : pr.state === 'closed' ? 2 : 0)
    return (
        [...reportPullRequests(report)].sort(
            (a, b) => rank(a) - rank(b) || a.url.toLowerCase().localeCompare(b.url.toLowerCase())
        )[0] ?? { id: null, url: '', state: 'unknown', merged: false }
    )
}

export function hasActiveReportPullRequest(report: ReportWithPullRequests | null | undefined): boolean {
    return reportPullRequests(report).some((pr) => !pr.merged && pr.state !== 'closed' && pr.state !== 'merged')
}

export function hasMergedReportPullRequest(report: ReportWithPullRequests | null | undefined): boolean {
    return reportPullRequests(report).some((pr) => pr.merged || pr.state === 'merged')
}
