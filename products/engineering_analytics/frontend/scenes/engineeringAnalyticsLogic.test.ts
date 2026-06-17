import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

import {
    engineeringAnalyticsCiCards,
    engineeringAnalyticsPullRequests,
    engineeringAnalyticsSources,
    engineeringAnalyticsWorkflowHealth,
} from '../generated/api'
import type {
    CICardSummaryApi,
    GitHubSourceApi,
    PullRequestListItemApi,
    WorkflowHealthItemApi,
} from '../generated/api.schemas'
import { ciStatusOf } from '../lib/ci'
import { summarizeLifecycle, workflowRuns } from '../lib/lifecycle'
import {
    DEFAULT_FILTERS,
    PullRequestRow,
    engineeringAnalyticsLogic,
    filterPullRequests,
    workflowTrendSeries,
} from './engineeringAnalyticsLogic'
import { sortRunsForTriage } from './pullRequestDetailLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsCiCards: jest.fn(),
    engineeringAnalyticsPrLifecycle: jest.fn(),
    engineeringAnalyticsPullRequests: jest.fn(),
    engineeringAnalyticsSources: jest.fn(),
    engineeringAnalyticsWorkflowHealth: jest.fn(),
}))

const mockCiCards = engineeringAnalyticsCiCards as jest.MockedFunction<typeof engineeringAnalyticsCiCards>
const mockPullRequests = engineeringAnalyticsPullRequests as jest.MockedFunction<
    typeof engineeringAnalyticsPullRequests
>
const mockWorkflowHealth = engineeringAnalyticsWorkflowHealth as jest.MockedFunction<
    typeof engineeringAnalyticsWorkflowHealth
>
const mockSources = engineeringAnalyticsSources as jest.MockedFunction<typeof engineeringAnalyticsSources>

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
        repo: { provider: 'github', owner: 'posthog', name: 'posthog' },
        daily: [{ day: '2026-05-30', run_count: 100, completed: 95, successes: 90 }],
        workflow_name: 'CI',
        run_count: 100,
        success_rate: 0.95,
        p50_seconds: 120,
        p95_seconds: 600,
        last_failure_at: '2026-05-30T00:00:00Z',
    },
]
const SOURCES: GitHubSourceApi[] = [
    { id: 'src-older', repo: 'posthog/posthog', prefix: 'older' },
    { id: 'src-newer', repo: 'posthog/posthog.com', prefix: 'website' },
]

describe('engineeringAnalyticsLogic', () => {
    let logic: ReturnType<typeof engineeringAnalyticsLogic.build>

    beforeEach(() => {
        initKeaTests()
        ApiConfig.setCurrentProjectId(1)
        jest.clearAllMocks()
        // Happy-path defaults; individual tests override before mounting where needed.
        mockCiCards.mockResolvedValue(CARDS)
        mockPullRequests.mockResolvedValue({ items: PRS, truncated: false, limit: PRS.length })
        mockWorkflowHealth.mockResolvedValue(WORKFLOWS)
        // Most tests are single- or no-source; the picker tests override with SOURCES.
        mockSources.mockResolvedValue([])
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
            makePr({ number: 4, state: 'open', isDraft: true }),
            makePr({ number: 5, state: 'closed' }),
        ]
        // The open lens includes drafts; Draft and Closed are narrower cuts.
        expect(filterPullRequests(rows, DEFAULT_FILTERS)).toHaveLength(3)
        expect(filterPullRequests(rows, { ...DEFAULT_FILTERS, state: 'merged' })).toHaveLength(1)
        expect(filterPullRequests(rows, { ...DEFAULT_FILTERS, state: 'draft' }).map((row) => row.number)).toEqual([4])
        expect(filterPullRequests(rows, { ...DEFAULT_FILTERS, state: 'closed' }).map((row) => row.number)).toEqual([5])
        expect(filterPullRequests(rows, { ...DEFAULT_FILTERS, state: 'all', author: 'bob' })).toHaveLength(2)
        expect(filterPullRequests(rows, { ...DEFAULT_FILTERS, state: 'all', repo: 'posthog/posthog-js' })).toHaveLength(
            1
        )
        expect(filterPullRequests(rows, { ...DEFAULT_FILTERS, state: 'all', ciStatus: 'failing' })).toHaveLength(1)
        expect(filterPullRequests(rows, { ...DEFAULT_FILTERS, state: 'all', search: 'bump' })).toHaveLength(1)
        expect(filterPullRequests(rows, { ...DEFAULT_FILTERS, state: 'all', search: '#2' })).toHaveLength(1)
    })

    it('stuckOnly keeps open, non-draft, non-bot PRs older than 7 days', () => {
        const now = dayjs('2026-06-11T00:00:00Z')
        const rows = [
            makePr({ number: 1, createdAt: '2026-06-01T00:00:00Z' }),
            makePr({ number: 2, createdAt: '2026-06-09T00:00:00Z' }),
            makePr({ number: 3, createdAt: '2026-06-01T00:00:00Z', isDraft: true }),
            makePr({ number: 4, createdAt: '2026-06-01T00:00:00Z', isBot: true }),
            makePr({ number: 5, createdAt: '2026-05-01T00:00:00Z', state: 'merged', mergedAt: '2026-06-10T00:00:00Z' }),
        ]
        const stuck = filterPullRequests(rows, { ...DEFAULT_FILTERS, stuckOnly: true }, now)
        expect(stuck.map((row) => row.number)).toEqual([1])
    })

    it('card filters toggle the matching view and back', async () => {
        logic = engineeringAnalyticsLogic()
        logic.mount()
        expect(logic.values.activeCard).toBe('open')

        logic.actions.applyCardFilter('failing')
        expect(logic.values.activeCard).toBe('failing')
        expect(logic.values.ciStatusFilter).toBe('failing')

        logic.actions.applyCardFilter('stuck')
        expect(logic.values.activeCard).toBe('stuck')
        expect(logic.values.stuckOnly).toBe(true)
        expect(logic.values.ciStatusFilter).toBe('all')
        // The stuck lens is an active filter — a filtered-to-zero table must offer "Clear filters".
        expect(logic.values.hasActiveFilters).toBe(true)

        // Clicking the active card returns to the plain open view.
        logic.actions.applyCardFilter('stuck')
        expect(logic.values.activeCard).toBe('open')
        expect(logic.values.stuckOnly).toBe(false)

        // Leaving the open backlog deactivates every card.
        logic.actions.applyCardFilter('failing')
        logic.actions.setStateFilter('merged')
        expect(logic.values.activeCard).toBeNull()
    })

    it('keeps filter state isolated per internal tab', () => {
        const tabA = engineeringAnalyticsLogic({ tabId: 'tab-a' })
        const tabB = engineeringAnalyticsLogic({ tabId: 'tab-b' })
        tabA.mount()
        tabB.mount()

        tabA.actions.setStateFilter('merged')

        expect(tabA.values.stateFilter).toBe('merged')
        expect(tabB.values.stateFilter).toBe(DEFAULT_FILTERS.state)
    })

    it('maps the three endpoints into typed rows and defaults to the open filter', async () => {
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
        expect(logic.values.workflowHealth[0].daily).toEqual([
            { day: '2026-05-30', runCount: 100, completed: 95, successes: 90 },
        ])
        // Default state filter is "open", so only the open PR survives.
        expect(logic.values.filteredPullRequests).toHaveLength(1)
        expect(logic.values.loadFailed).toBe(false)
    })

    it('reloads workflow health when the date range changes', async () => {
        logic = engineeringAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowHealthSuccess'])
        expect(mockWorkflowHealth).toHaveBeenLastCalledWith('1', { date_from: '-30d' })

        logic.actions.setWorkflowDateRange('-90d', null)
        await expectLogic(logic).toDispatchActions(['loadWorkflowHealth', 'loadWorkflowHealthSuccess'])
        expect(mockWorkflowHealth).toHaveBeenLastCalledWith('1', { date_from: '-90d' })

        logic.actions.setWorkflowDateRange('2026-01-01', '2026-03-01')
        await expectLogic(logic).toDispatchActions(['loadWorkflowHealthSuccess'])
        expect(mockWorkflowHealth).toHaveBeenLastCalledWith('1', { date_from: '2026-01-01', date_to: '2026-03-01' })
    })

    it('exposes source options and the multi-source flag only when more than one source exists', async () => {
        mockSources.mockResolvedValue(SOURCES)
        logic = engineeringAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadGithubSourcesSuccess'])

        expect(logic.values.hasMultipleSources).toBe(true)
        expect(logic.values.sourceOptions).toEqual([
            { value: 'src-older', label: 'posthog/posthog' },
            { value: 'src-newer', label: 'posthog/posthog.com' },
        ])
    })

    it('hides the picker when the team has a single source', async () => {
        mockSources.mockResolvedValue([SOURCES[0]])
        logic = engineeringAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadGithubSourcesSuccess'])

        expect(logic.values.hasMultipleSources).toBe(false)
    })

    it('defaults to no source, then scopes every endpoint to the picked one and reloads', async () => {
        logic = engineeringAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions([
            'loadCardsSuccess',
            'loadPullRequestsSuccess',
            'loadWorkflowHealthSuccess',
        ])
        // No source picked → omit source_id so the backend resolves its default.
        expect(mockCiCards).toHaveBeenLastCalledWith('1', { source_id: undefined })

        logic.actions.setSourceId('src-newer')
        await expectLogic(logic).toDispatchActions([
            'setSourceId',
            'loadCards',
            'loadPullRequests',
            'loadWorkflowHealth',
            'loadCardsSuccess',
        ])

        expect(logic.values.sourceId).toBe('src-newer')
        expect(mockCiCards).toHaveBeenLastCalledWith('1', { source_id: 'src-newer' })
        expect(mockPullRequests).toHaveBeenLastCalledWith('1', { source_id: 'src-newer' })
        expect(mockWorkflowHealth).toHaveBeenLastCalledWith('1', { date_from: '-30d', source_id: 'src-newer' })
    })

    it('resetFilters returns every filter to defaults and clears hasActiveFilters', async () => {
        logic = engineeringAnalyticsLogic()
        logic.mount()
        expect(logic.values.hasActiveFilters).toBe(false)

        logic.actions.setStateFilter('all')
        logic.actions.setAuthor('alice')
        logic.actions.setRepo('posthog/posthog')
        logic.actions.setCiStatusFilter('failing')
        logic.actions.setSearch('fix')
        expect(logic.values.hasActiveFilters).toBe(true)

        logic.actions.resetFilters()
        expect(logic.values.filters).toEqual(DEFAULT_FILTERS)
        expect(logic.values.hasActiveFilters).toBe(false)
    })

    it.each([
        ['a bad day spikes', { completed: 25, successes: 22 }, 0.12, 'Jun 5 · 3 of 25 non-passing'],
        ['an all-green day stays flat', { completed: 25, successes: 25 }, 0, 'Jun 5 · 0 of 25 non-passing'],
        ['a day with nothing completed stays flat', { completed: 0, successes: 0 }, 0, 'Jun 5 · no completed runs'],
    ])('workflowTrendSeries: %s', (_label, counts, value, label) => {
        const series = workflowTrendSeries([{ day: '2026-06-05', runCount: 30, ...counts }])
        expect(series).toEqual({ values: [value], labels: [label] })
    })

    it('summarizeLifecycle rolls events up into milestones and verdicts', () => {
        const summary = summarizeLifecycle([
            { kind: 'opened', at: '2026-06-01T00:00:00Z' },
            { kind: 'ci_started', at: '2026-06-01T00:01:00Z', detail: 'Backend CI' },
            { kind: 'ci_started', at: '2026-06-01T00:02:00Z', detail: 'Frontend CI' },
            { kind: 'ci_started', at: '2026-06-01T00:03:00Z', detail: 'E2E: smoke' },
            { kind: 'ci_finished', at: '2026-06-01T00:30:00Z', detail: 'Backend CI: failure' },
            { kind: 'ci_finished', at: '2026-06-01T00:20:00Z', detail: 'Frontend CI: success' },
            { kind: 'merged', at: '2026-06-02T00:00:00Z' },
        ])
        expect(summary.openedAt).toBe('2026-06-01T00:00:00Z')
        expect(summary.firstCiStartedAt).toBe('2026-06-01T00:01:00Z')
        expect(summary.lastCiFinishedAt).toBe('2026-06-01T00:30:00Z')
        expect(summary.mergedAt).toBe('2026-06-02T00:00:00Z')
        expect(summary.closedAt).toBeNull()
        expect(summary.notPassing).toEqual([
            { workflow: 'Backend CI', conclusion: 'failure', at: '2026-06-01T00:30:00Z' },
        ])
        expect(summary.passed).toBe(1)
        expect(summary.unsettled).toBe(1)
    })

    it('summarizeLifecycle keeps workflow names that contain a colon', () => {
        const summary = summarizeLifecycle([
            { kind: 'ci_finished', at: '2026-06-01T00:30:00Z', detail: 'E2E: smoke: timed_out' },
        ])
        expect(summary.notPassing).toEqual([
            { workflow: 'E2E: smoke', conclusion: 'timed_out', at: '2026-06-01T00:30:00Z' },
        ])
    })

    it('workflowRuns pairs starts and finishes into per-workflow runs with durations', () => {
        const runs = workflowRuns([
            { kind: 'opened', at: '2026-06-01T00:00:00Z' },
            { kind: 'ci_started', at: '2026-06-01T00:01:00Z', detail: 'Backend CI', run_id: 9001 },
            { kind: 'ci_started', at: '2026-06-01T00:01:30Z', detail: 'Frontend CI' },
            { kind: 'ci_started', at: '2026-06-01T01:00:00Z', detail: 'Backend CI', run_id: 9002 },
            { kind: 'ci_finished', at: '2026-06-01T00:31:00Z', detail: 'Backend CI: failure', run_id: 9001 },
            { kind: 'ci_finished', at: '2026-06-01T01:20:00Z', detail: 'Backend CI: success', run_id: 9002 },
            { kind: 'ci_finished', at: '2026-06-01T00:10:00Z', detail: 'Orphan CI: success', run_id: 9003 },
        ])
        expect(runs).toEqual([
            // First Backend CI start pairs with the first Backend CI finish (FIFO across re-runs).
            {
                workflow: 'Backend CI',
                conclusion: 'failure',
                startedAt: '2026-06-01T00:01:00Z',
                finishedAt: '2026-06-01T00:31:00Z',
                durationSeconds: 1800,
                runId: 9001,
            },
            {
                workflow: 'Frontend CI',
                conclusion: null,
                startedAt: '2026-06-01T00:01:30Z',
                finishedAt: null,
                durationSeconds: null,
                runId: null,
            },
            {
                workflow: 'Backend CI',
                conclusion: 'success',
                startedAt: '2026-06-01T01:00:00Z',
                finishedAt: '2026-06-01T01:20:00Z',
                durationSeconds: 1200,
                runId: 9002,
            },
            // A finish without a matching start (outside the window) still yields a row.
            {
                workflow: 'Orphan CI',
                conclusion: 'success',
                startedAt: null,
                finishedAt: '2026-06-01T00:10:00Z',
                durationSeconds: null,
                runId: 9003,
            },
        ])
        // The detail page triages: failures first, then still-running, then passes.
        expect(sortRunsForTriage(runs).map((run) => run.conclusion)).toEqual(['failure', null, 'success', 'success'])
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
