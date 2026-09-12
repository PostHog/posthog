import type { SignalReportPullRequestApi } from 'products/signals/frontend/generated/api.schemas'

import {
    reportPullRequests,
    primaryReportPullRequest,
    hasActiveReportPullRequest,
    hasMergedReportPullRequest,
} from './reportPullRequests'

describe('report pull request consumers', () => {
    const pr = (url: string, state: 'open' | 'closed' | 'merged'): SignalReportPullRequestApi => ({
        id: url,
        url,
        state,
        merged: state === 'merged',
        claim_id: null,
        attached_at: null,
        attached_by: null,
    })
    const report = {
        implementation_pr_url: 'https://github.com/example/app/pull/1',
        implementation_pr_merged: true,
        pull_requests: [
            pr('https://github.com/example/app/pull/1', 'merged'),
            pr('https://github.com/example/app/pull/2', 'open'),
        ],
    }
    it('uses all linked PRs even when the legacy primary has merged', () => {
        expect(reportPullRequests(report)).toHaveLength(2)
        expect(primaryReportPullRequest(report).url).toBe('https://github.com/example/app/pull/2')
        expect(hasActiveReportPullRequest(report)).toBe(true)
        expect(hasMergedReportPullRequest(report)).toBe(true)
    })
    it('does not resurrect stale legacy fields when the collection is empty', () => {
        const empty = { ...report, pull_requests: [] }
        expect(reportPullRequests(empty)).toEqual([])
        expect(primaryReportPullRequest(empty).url).toBe('')
        expect(hasActiveReportPullRequest(empty)).toBe(false)
    })
    it('supports old servers but does not treat a closed PR as active', () => {
        expect(reportPullRequests({ implementation_pr_url: report.implementation_pr_url })).toHaveLength(1)
        expect(hasActiveReportPullRequest({ pull_requests: [pr(report.implementation_pr_url, 'closed')] })).toBe(false)
    })
    it('selects the same primary regardless of attachment order', () => {
        expect(primaryReportPullRequest(report)).toEqual(
            primaryReportPullRequest({ ...report, pull_requests: [...report.pull_requests].reverse() })
        )
    })
})
