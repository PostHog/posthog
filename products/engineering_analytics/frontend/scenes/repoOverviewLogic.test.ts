import { PullRequestRow } from './engineeringAnalyticsLogic'
import { computeAuthorStats } from './repoOverviewLogic'

function pr(overrides: Partial<PullRequestRow>): PullRequestRow {
    return {
        number: 1,
        title: 'a change',
        repoOwner: 'PostHog',
        repoName: 'posthog',
        authorHandle: 'alice',
        authorAvatarUrl: '',
        isBot: false,
        state: 'open',
        isDraft: false,
        createdAt: '2026-06-01T00:00:00Z',
        mergedAt: null,
        openToMergeSeconds: null,
        labels: [],
        runs: 0,
        passing: 0,
        failing: 0,
        pending: 0,
        failingWorkflows: [],
        pushes: 1,
        rerunCycles: 0,
        estimatedCostUsd: null,
        billableMinutes: null,
        ...overrides,
    }
}

describe('computeAuthorStats', () => {
    it('excludes bots from the leaderboard entirely', () => {
        const rows = computeAuthorStats([
            pr({ authorHandle: 'alice' }),
            pr({ authorHandle: 'posthog[bot]', isBot: true }),
            pr({ authorHandle: 'posthog[bot]', isBot: true }),
        ])
        expect(rows.map((r) => r.handle)).toEqual(['alice'])
    })

    it('keeps cost null when none of the PRs carry cost, instead of a misleading $0', () => {
        const [alice] = computeAuthorStats([pr({}), pr({ number: 2 })])
        expect(alice.costUsd).toBeNull()
    })

    it('aggregates per author: counts, summed cost, and the median over merged PRs only', () => {
        const [alice] = computeAuthorStats([
            pr({ number: 1, openToMergeSeconds: 100, estimatedCostUsd: 1.5 }),
            pr({ number: 2, openToMergeSeconds: 300, estimatedCostUsd: 0.5 }),
            pr({ number: 3, openToMergeSeconds: null }),
        ])
        expect(alice.prCount).toBe(3)
        expect(alice.costUsd).toBeCloseTo(2.0)
        // Even count of merge times → the mean of the middle pair; unmerged PRs don't dilute it.
        expect(alice.medianOpenToMergeSeconds).toBe(200)
    })
})
