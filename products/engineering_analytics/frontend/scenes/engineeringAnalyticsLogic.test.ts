import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'

import { initKeaTests } from '~/test/init'

import {
    engineeringAnalyticsCiCards,
    engineeringAnalyticsPullRequests,
    engineeringAnalyticsWorkflowHealth,
} from '../generated/api'
import type { CICardSummaryApi, PullRequestListItemApi, WorkflowHealthItemApi } from '../generated/api.schemas'
import { ciStatusOf } from '../lib/ci'
import { PullRequestRow, engineeringAnalyticsLogic, filterPullRequests } from './engineeringAnalyticsLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsCiCards: jest.fn(),
    engineeringAnalyticsPullRequests: jest.fn(),
    engineeringAnalyticsWorkflowHealth: jest.fn(),
}))

const mockCiCards = engineeringAnalyticsCiCards as jest.MockedFunction<typeof engineeringAnalyticsCiCards>
const mockPullRequests = engineeringAnalyticsPullRequests as jest.MockedFunction<
    typeof engineeringAnalyticsPullRequests
>
const mockWorkflowHealth = engineeringAnalyticsWorkflowHealth as jest.MockedFunction<
    typeof engineeringAnalyticsWorkflowHealth
>

function makePr(overrides: Partial<PullRequestRow> = {}): PullRequestRow {
    return {
        number: 1,
        title: 'feat: a thing',
        repoOwner: 'posthog',
        repoName: 'posthog',
        authorHandle: 'alice',
        authorAvatarUrl: '',
        isBot: false,
        state: 'open',
        isDraft: false,
        createdAt: '2026-05-01T00:00:00Z',
        mergedAt: null,
        openToMergeSeconds: null,
        labels: [],
        runs: 0,
        passing: 0,
        failing: 0,
        pending: 0,
        ...overrides,
    }
}

function apiPr(overrides: Partial<PullRequestListItemApi> = {}): PullRequestListItemApi {
    return {
        author: { handle: 'alice', display_name: 'alice', avatar_url: 'https://a/avatar', is_bot: false },
        repo: { provider: 'github', owner: 'posthog', name: 'posthog' },
        ci: { runs: 0, passing: 0, failing: 0, pending: 0 },
        number: 1,
        title: 'feat: x',
        state: 'open',
        is_draft: false,
        created_at: '2026-05-01T00:00:00Z',
        merged_at: null,
        open_to_merge_seconds: null,
        labels: [],
        ...overrides,
    }
}

const CARDS: CICardSummaryApi = { open_prs: 18, repos: 10, stuck: 6, failing_ci: 4 }
const PRS: PullRequestListItemApi[] = [
    apiPr({ number: 101, ci: { runs: 3, passing: 2, failing: 1, pending: 0 } }),
    apiPr({
        number: 102,
        title: 'fix: y',
        author: { handle: 'bob', display_name: 'bob', avatar_url: 'https://b/avatar', is_bot: false },
        repo: { provider: 'github', owner: 'posthog', name: 'posthog-js' },
        ci: { runs: 5, passing: 5, failing: 0, pending: 0 },
        state: 'merged',
        created_at: '2026-05-20T00:00:00Z',
        merged_at: '2026-05-21T00:00:00Z',
        open_to_merge_seconds: 86400,
    }),
]
const WORKFLOWS: WorkflowHealthItemApi[] = [
    {
        workflow_name: 'CI',
        run_count: 100,
        success_rate: 0.95,
        p50_seconds: 120,
        p95_seconds: 600,
        last_failure_at: '2026-05-30T00:00:00Z',
    },
]

describe('engineeringAnalyticsLogic', () => {
    let logic: ReturnType<typeof engineeringAnalyticsLogic.build>

    beforeEach(() => {
        initKeaTests()
        ApiConfig.setCurrentProjectId(1)
        jest.clearAllMocks()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        ['no runs', { runs: 0, failing: 0, pending: 0 }, 'none'],
        ['a failure', { runs: 3, failing: 1, pending: 0 }, 'failing'],
        ['failure beats pending', { runs: 5, failing: 1, pending: 2 }, 'failing'],
        ['unsettled run', { runs: 3, failing: 0, pending: 2 }, 'running'],
        ['all green', { runs: 3, failing: 0, pending: 0 }, 'passing'],
    ])('ciStatusOf derives %s', (_label, rollup, expected) => {
        expect(ciStatusOf(rollup)).toBe(expected)
    })

    it('filters by state, author, repo, ci status, and search', () => {
        const rows = [
            makePr({ number: 1, state: 'open', authorHandle: 'alice', runs: 2, failing: 1 }),
            makePr({ number: 2, state: 'merged', authorHandle: 'bob', repoName: 'posthog-js' }),
            makePr({ number: 3, state: 'open', authorHandle: 'bob', title: 'chore: bump' }),
        ]
        expect(
            filterPullRequests(rows, { state: 'open', author: null, repo: null, ciStatus: 'all', search: '' })
        ).toHaveLength(2)
        expect(
            filterPullRequests(rows, { state: 'merged', author: null, repo: null, ciStatus: 'all', search: '' })
        ).toHaveLength(1)
        expect(
            filterPullRequests(rows, { state: 'all', author: 'bob', repo: null, ciStatus: 'all', search: '' })
        ).toHaveLength(2)
        expect(
            filterPullRequests(rows, {
                state: 'all',
                author: null,
                repo: 'posthog/posthog-js',
                ciStatus: 'all',
                search: '',
            })
        ).toHaveLength(1)
        expect(
            filterPullRequests(rows, { state: 'all', author: null, repo: null, ciStatus: 'failing', search: '' })
        ).toHaveLength(1)
        expect(
            filterPullRequests(rows, { state: 'all', author: null, repo: null, ciStatus: 'all', search: 'bump' })
        ).toHaveLength(1)
        expect(
            filterPullRequests(rows, { state: 'all', author: null, repo: null, ciStatus: 'all', search: '#2' })
        ).toHaveLength(1)
    })

    it('maps the three endpoints into typed rows and defaults to the open filter', async () => {
        mockCiCards.mockResolvedValue(CARDS)
        mockPullRequests.mockResolvedValue({ items: PRS, truncated: false, limit: PRS.length })
        mockWorkflowHealth.mockResolvedValue(WORKFLOWS)

        logic = engineeringAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadCardsSuccess',
            'loadPullRequestsSuccess',
            'loadWorkflowHealthSuccess',
        ])

        expect(logic.values.cards).toEqual({ openPrs: 18, repos: 10, stuck: 6, failingCi: 4 })
        expect(logic.values.pullRequests).toHaveLength(2)
        expect(logic.values.pullRequests[0].authorHandle).toBe('alice')
        expect(ciStatusOf(logic.values.pullRequests[0])).toBe('failing')
        expect(logic.values.pullRequests[1].openToMergeSeconds).toBe(86400)
        expect(logic.values.workflowHealth).toHaveLength(1)
        expect(logic.values.workflowHealth[0].successRate).toBe(0.95)
        // Default state filter is "open", so only the open PR survives.
        expect(logic.values.filteredPullRequests).toHaveLength(1)
        expect(logic.values.loadFailed).toBe(false)
    })

    it('flags loadFailed when no GitHub source is connected (cards endpoint 400s)', async () => {
        mockCiCards.mockRejectedValue(new Error('Connect a GitHub data warehouse source to use engineering analytics.'))
        mockPullRequests.mockResolvedValue({ items: [], truncated: false, limit: 0 })
        mockWorkflowHealth.mockResolvedValue([])

        logic = engineeringAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadCardsFailure'])

        expect(logic.values.loadFailed).toBe(true)
    })
})
