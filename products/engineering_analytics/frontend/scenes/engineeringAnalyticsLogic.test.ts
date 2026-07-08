import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { ApiConfig, ApiError } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import {
    engineeringAnalyticsCiCards,
    engineeringAnalyticsPullRequests,
    engineeringAnalyticsQuarantine,
    engineeringAnalyticsQuarantineRequest,
    engineeringAnalyticsSources,
    engineeringAnalyticsWorkflowHealth,
} from '../generated/api'
import type {
    CICardSummaryApi,
    GitHubSourceApi,
    PullRequestListItemApi,
    QuarantineEntryApi,
    QuarantineFileApi,
    WorkflowHealthItemApi,
    WorkflowRunDetailApi,
} from '../generated/api.schemas'
import { ciStatusOf } from '../lib/ci'
import { summarizeLifecycle, workflowRuns } from '../lib/lifecycle'
import { engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'
import {
    DEFAULT_FILTERS,
    DEFAULT_QUARANTINE_FILTERS,
    DEFAULT_WORKFLOW_FILTERS,
    PullRequestRow,
    QuarantineEntryRow,
    WorkflowHealthRow,
    engineeringAnalyticsLogic,
    filterPullRequests,
    filterWorkflowHealth,
    workflowFailureSeries,
    filterQuarantineEntries,
    inferOwnerFromSelector,
    quarantineCountsOf,
    quarantineRequestErrorMessage,
} from './engineeringAnalyticsLogic'
import { engineeringAnalyticsSceneLogic } from './engineeringAnalyticsSceneLogic'
import { groupRunsByCommit, sortRunsForTriage } from './pullRequestDetailLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsCiCards: jest.fn(),
    engineeringAnalyticsPrLifecycle: jest.fn(),
    engineeringAnalyticsPullRequests: jest.fn(),
    engineeringAnalyticsQuarantine: jest.fn(),
    engineeringAnalyticsQuarantineRequest: jest.fn(),
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
const mockQuarantine = engineeringAnalyticsQuarantine as jest.MockedFunction<typeof engineeringAnalyticsQuarantine>
const mockQuarantineRequest = engineeringAnalyticsQuarantineRequest as jest.MockedFunction<
    typeof engineeringAnalyticsQuarantineRequest
>
const mockSources = engineeringAnalyticsSources as jest.MockedFunction<typeof engineeringAnalyticsSources>

function apiQuarantineEntry(overrides: Partial<QuarantineEntryApi> = {}): QuarantineEntryApi {
    return {
        id: 'posthog/api/test/test_foo.py::TestFoo::test_bar',
        runner: 'pytest',
        reason: 'flaky ordering assertion',
        owner: '@PostHog/team-foo',
        issue: '',
        added: '2026-06-01',
        expires: '2026-06-20',
        mode: 'run',
        lifecycle: 'active',
        days_until_expiry: 8,
        selector_kind: 'test',
        ...overrides,
    }
}

function qRow(overrides: Partial<QuarantineEntryRow> = {}): QuarantineEntryRow {
    return {
        id: 'posthog/api/test/test_foo.py::TestFoo::test_bar',
        runner: 'pytest',
        reason: 'flaky',
        owner: '@PostHog/team-foo',
        issue: '',
        added: '2026-06-01',
        expires: '2026-06-20',
        mode: 'run',
        lifecycle: 'active',
        daysUntilExpiry: 8,
        selectorKind: 'test',
        ...overrides,
    }
}

const QUARANTINE: QuarantineFileApi = {
    available: true,
    entries: [
        apiQuarantineEntry({ id: 'a-overdue', lifecycle: 'overdue', days_until_expiry: -10, owner: '@team/x' }),
        apiQuarantineEntry({ id: 'b-grace', lifecycle: 'in_grace', days_until_expiry: -2, owner: '@team/y' }),
        apiQuarantineEntry({ id: 'c-soon', lifecycle: 'expiring_soon', days_until_expiry: 3, owner: '@team/x' }),
        apiQuarantineEntry({ id: 'd-active', lifecycle: 'active', days_until_expiry: 20, owner: '@team/z' }),
        apiQuarantineEntry({
            id: 'product:e',
            lifecycle: 'active',
            mode: 'skip',
            selector_kind: 'product',
            owner: '@team/z',
            reason: 'teardown hang',
        }),
    ],
    parse_errors: [],
    parse_warnings: [],
    repo: { provider: 'github', owner: 'PostHog', name: 'posthog' },
    source_url: 'https://github.com/PostHog/posthog/blob/HEAD/.test_quarantine.json',
    generated_at: '2026-06-12T00:00:00Z',
}

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
        failingWorkflows: [],
        pushes: 0,
        rerunCycles: 0,
        estimatedCostUsd: null,
        billableMinutes: null,
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
        pushes: 0,
        rerun_cycles: 0,
        estimated_cost_usd: null,
        ...overrides,
    }
}

const CARDS: CICardSummaryApi = { open_prs: 18, repos: 10, stuck: 6, failing_ci: 4 }
const PRS: PullRequestListItemApi[] = [
    apiPr({ number: 101, ci: { runs: 3, passing: 2, failing: 1, pending: 0 }, pushes: 7, rerun_cycles: 2 }),
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
        granularity: 'day',
        buckets: [{ bucket_start: '2026-05-30T00:00:00Z', run_count: 100, completed: 95, successes: 90, failures: 4 }],
        workflow_name: 'CI',
        run_count: 100,
        success_rate: 0.95,
        p50_seconds: 120,
        p95_seconds: 600,
        last_failure_at: '2026-05-30T00:00:00Z',
        latest_run_failed: false,
        latest_run_conclusion: 'success',
    },
]
function makeWorkflow(overrides: Partial<WorkflowHealthRow> = {}): WorkflowHealthRow {
    return {
        repoOwner: 'posthog',
        repoName: 'posthog',
        workflowName: 'CI',
        runCount: 10,
        successRate: 1,
        p50Seconds: 60,
        p95Seconds: 120,
        lastFailureAt: null,
        latestRunFailed: false,
        latestRunConclusion: 'success',
        granularity: 'day',
        buckets: [],
        ...overrides,
    }
}

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
        mockQuarantine.mockResolvedValue(QUARANTINE)
        mockQuarantineRequest.mockResolvedValue({
            pr_url: 'https://github.com/PostHog/posthog/pull/99',
            issue_url: 'https://github.com/PostHog/posthog/issues/4242',
            branch: 'quarantine/foo-20260612',
        })
        // Most tests are single- or no-source; the picker tests override with SOURCES.
        mockSources.mockResolvedValue([])
    })

    afterEach(() => {
        jest.restoreAllMocks()
        resumeKeaLoadersErrors()
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

    it('scene logic mounts without a tabId so /engineering-analytics resolves instead of 404ing', () => {
        // #62051 collapsed sceneLogic to single-scene state and stopped threading a tabId into
        // scene logics. A tab-aware scene logic then throws "must have a tabId prop" on mount,
        // sceneLogic's catch falls back to Error404, and every visit to the scene 404s.
        expect(() => engineeringAnalyticsSceneLogic().mount()).not.toThrow()
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
        expect(logic.values.pullRequests[0].pushes).toBe(7)
        expect(logic.values.pullRequests[0].rerunCycles).toBe(2)
        expect(logic.values.pullRequests[0].estimatedCostUsd).toBeNull()
        expect(logic.values.pullRequests[1].openToMergeSeconds).toBe(86400)
        expect(logic.values.workflowHealth).toHaveLength(1)
        expect(logic.values.workflowHealth[0].successRate).toBe(0.95)
        expect(logic.values.workflowHealth[0].latestRunFailed).toBe(false)
        expect(logic.values.workflowHealth[0].granularity).toBe('day')
        expect(logic.values.workflowHealth[0].buckets).toEqual([
            { bucketStart: '2026-05-30T00:00:00Z', runCount: 100, completed: 95, successes: 90, failures: 4 },
        ])
        // Default state filter is "open", so only the open PR survives.
        expect(logic.values.filteredPullRequests).toHaveLength(1)
        expect(logic.values.notConnected).toBe(false)
        expect(logic.values.pullRequestsLoadError).toBe(false)
        expect(logic.values.workflowHealthLoadError).toBe(false)
    })

    it('reloads workflow health when the shared date range changes', async () => {
        logic = engineeringAnalyticsLogic()
        logic.mount()
        const filters = engineeringAnalyticsFiltersLogic()
        filters.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowHealthSuccess'])
        expect(mockWorkflowHealth).toHaveBeenLastCalledWith('1', { date_from: '-7d' })

        filters.actions.setDateRange('-90d', null)
        await expectLogic(logic).toDispatchActions(['loadWorkflowHealth', 'loadWorkflowHealthSuccess'])
        expect(mockWorkflowHealth).toHaveBeenLastCalledWith('1', { date_from: '-90d' })

        filters.actions.setDateRange('2026-01-01', '2026-03-01')
        await expectLogic(logic).toDispatchActions(['loadWorkflowHealthSuccess'])
        expect(mockWorkflowHealth).toHaveBeenLastCalledWith('1', { date_from: '2026-01-01', date_to: '2026-03-01' })
    })

    it('filters workflow health by the shared branch scope, only reloading on a real change', async () => {
        // Branch lives in the shared filters logic (so it carries into the workflow detail page); the
        // Workflows tab reads it and reloads workflow health when it's applied.
        logic = engineeringAnalyticsLogic()
        logic.mount()
        const filters = engineeringAnalyticsFiltersLogic()
        filters.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowHealthSuccess'])
        expect(mockWorkflowHealth).toHaveBeenLastCalledWith('1', { date_from: '-7d' })

        // Typing only stages the value — no reload until applied.
        filters.actions.setBranchFilter('main')
        expect(filters.values.branchInput).toBe('main')
        expect(filters.values.appliedBranch).toBe('')

        // Applying promotes it and reloads with the branch param (trimmed).
        filters.actions.setBranchFilter('  main  ')
        filters.actions.applyBranchFilter()
        await expectLogic(logic).toDispatchActions(['loadWorkflowHealth', 'loadWorkflowHealthSuccess'])
        expect(filters.values.appliedBranch).toBe('main')
        expect(mockWorkflowHealth).toHaveBeenLastCalledWith('1', { date_from: '-7d', branch: 'main' })

        // Re-applying an unchanged value (e.g. a blur with no edit) does not reload.
        mockWorkflowHealth.mockClear()
        filters.actions.applyBranchFilter()
        await expectLogic(logic).toNotHaveDispatchedActions(['loadWorkflowHealth'])
        expect(mockWorkflowHealth).not.toHaveBeenCalled()

        // The applied branch persists across a date-range reload.
        filters.actions.setDateRange('-90d', null)
        await expectLogic(logic).toDispatchActions(['loadWorkflowHealthSuccess'])
        expect(mockWorkflowHealth).toHaveBeenLastCalledWith('1', { date_from: '-90d', branch: 'main' })

        // Clearing the box (e.g. the search × button, which only fires onChange('')) applies
        // immediately — no Enter/blur needed — and drops the filter.
        filters.actions.setBranchFilter('')
        await expectLogic(logic).toDispatchActions(['loadWorkflowHealthSuccess'])
        expect(filters.values.appliedBranch).toBe('')
        expect(mockWorkflowHealth).toHaveBeenLastCalledWith('1', { date_from: '-90d' })
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
        expect(mockWorkflowHealth).toHaveBeenLastCalledWith('1', { date_from: '-7d', source_id: 'src-newer' })
    })

    it.each([
        // 'failing'/'passing' key off the latest settled run; a row with nothing completed
        // (latestRunFailed null) must show only under 'all' — it is neither green nor red.
        ['failing keeps only rows whose latest run failed', { status: 'failing' as const }, ['E2E']],
        ['passing keeps only settled green rows', { status: 'passing' as const }, ['CI']],
        ['unsettled rows show only under all', {}, ['CI', 'E2E', 'Nightly']],
        ['search is case-insensitive over the name', { search: 'NIGHT' }, ['Nightly']],
    ])('filterWorkflowHealth: %s', (_label, overrides, expected) => {
        const rows = [
            makeWorkflow({ workflowName: 'CI', latestRunFailed: false }),
            makeWorkflow({ workflowName: 'E2E', latestRunFailed: true }),
            makeWorkflow({ workflowName: 'Nightly', latestRunFailed: null, latestRunConclusion: null }),
        ]
        expect(
            filterWorkflowHealth(rows, { ...DEFAULT_WORKFLOW_FILTERS, ...overrides }).map((row) => row.workflowName)
        ).toEqual(expected)
    })

    it('resetWorkflowFilters returns the workflow filters to defaults and clears hasActiveWorkflowFilters', () => {
        logic = engineeringAnalyticsLogic()
        logic.mount()
        expect(logic.values.hasActiveWorkflowFilters).toBe(false)

        logic.actions.setWorkflowSearch('e2e')
        logic.actions.setWorkflowStatusFilter('failing')
        expect(logic.values.hasActiveWorkflowFilters).toBe(true)

        logic.actions.resetWorkflowFilters()
        expect(logic.values.workflowFilters).toEqual(DEFAULT_WORKFLOW_FILTERS)
        expect(logic.values.hasActiveWorkflowFilters).toBe(false)
    })

    it('workflowCostAvailable flips on once any row carries cost data', async () => {
        logic = engineeringAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowHealthSuccess'])
        expect(logic.values.workflowCostAvailable).toBe(false)

        mockWorkflowHealth.mockResolvedValue([{ ...WORKFLOWS[0], billable_minutes: 12, estimated_cost_usd: 0.5 }])
        logic.actions.loadWorkflowHealth()
        await expectLogic(logic).toDispatchActions(['loadWorkflowHealthSuccess'])
        expect(logic.values.workflowCostAvailable).toBe(true)
    })

    it.each([
        ['workflows', () => urls.engineeringAnalyticsWorkflows()],
        ['test health', () => urls.engineeringAnalyticsTestHealth()],
    ])('the %s route applies ?source like the other tabs', async (_label, url) => {
        logic = engineeringAnalyticsLogic()
        logic.mount()

        router.actions.push(url(), { source: 'src-newer' })
        await expectLogic(logic).toDispatchActions(['setSourceId'])
        expect(logic.values.sourceId).toBe('src-newer')
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
        // Stacked bar: total height is completed (volume), the red portion is failures, so the red
        // fraction reads as the rate. Skipped/cancelled/action_required are completed but not failures.
        [
            'a bad day stacks failures over completed',
            { completed: 25, successes: 22, failures: 3 },
            25,
            3,
            'Jun 5 · 3 of 25 failed',
        ],
        ['an all-green day has no red', { completed: 25, successes: 25, failures: 0 }, 25, 0, 'Jun 5 · 0 of 25 failed'],
        [
            'skipped/cancelled runs are not failures',
            { completed: 25, successes: 20, failures: 0 },
            25,
            0,
            'Jun 5 · 0 of 25 failed',
        ],
        [
            'a bucket with nothing completed is empty',
            { completed: 0, successes: 0, failures: 0 },
            0,
            0,
            'Jun 5 · no completed runs',
        ],
    ])('workflowFailureSeries: %s', (_label, counts, completed, failures, label) => {
        const series = workflowFailureSeries([{ bucketStart: '2026-06-05', runCount: 30, ...counts }], 'day')
        expect(series).toEqual({ completed: [completed], failures: [failures], labels: [label] })
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
                runAttempt: null,
            },
            {
                workflow: 'Frontend CI',
                conclusion: null,
                startedAt: '2026-06-01T00:01:30Z',
                finishedAt: null,
                durationSeconds: null,
                runId: null,
                runAttempt: null,
            },
            {
                workflow: 'Backend CI',
                conclusion: 'success',
                startedAt: '2026-06-01T01:00:00Z',
                finishedAt: '2026-06-01T01:20:00Z',
                durationSeconds: 1200,
                runId: 9002,
                runAttempt: null,
            },
            // A finish without a matching start (outside the window) still yields a row.
            {
                workflow: 'Orphan CI',
                conclusion: 'success',
                startedAt: null,
                finishedAt: '2026-06-01T00:10:00Z',
                durationSeconds: null,
                runId: 9003,
                runAttempt: null,
            },
        ])
        // The detail page triages: failures first, then still-running, then passes.
        expect(sortRunsForTriage(runs).map((run) => run.conclusion)).toEqual(['failure', null, 'success', 'success'])
    })

    it('groupRunsByCommit groups by head SHA, newest push first', () => {
        const apiRun = (overrides: Partial<WorkflowRunDetailApi>): WorkflowRunDetailApi => ({
            repo: { provider: 'github', owner: 'posthog', name: 'posthog' },
            id: 1,
            workflow_name: 'CI',
            head_sha: 'sha',
            head_branch: 'main',
            status: 'completed',
            conclusion: 'success',
            run_started_at: '2026-06-01T00:00:00Z',
            updated_at: '2026-06-01T00:05:00Z',
            duration_seconds: 300,
            run_attempt: 1,
            pr_number: 10,
            ...overrides,
        })
        const groups = groupRunsByCommit([
            apiRun({ id: 1, head_sha: 'old', run_started_at: '2026-06-01T00:00:00Z' }),
            apiRun({ id: 2, head_sha: 'old', run_started_at: '2026-06-01T00:01:00Z' }),
            apiRun({ id: 3, head_sha: 'new', run_started_at: '2026-06-02T00:00:00Z' }),
        ])
        // Newest push (latest start) first; runs map into WorkflowRun shape under their commit.
        expect(groups.map((g) => g.headSha)).toEqual(['new', 'old'])
        expect(groups[1].runs.map((r) => r.runId)).toEqual([1, 2])
    })

    it('flags notConnected when no GitHub source is connected (cards 400s)', async () => {
        silenceKeaLoadersErrors() // the 400 loader failure is the scenario under test
        mockCiCards.mockRejectedValue(
            new ApiError('Connect a GitHub data warehouse source to use engineering analytics.', 400)
        )
        logic = engineeringAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadCardsFailure'])

        expect(logic.values.notConnected).toBe(true)
        expect(logic.values.pullRequestsLoadError).toBe(false)
        expect(logic.values.workflowHealthLoadError).toBe(false)
    })

    it('flags notConnected from the workflow-health loader too (the Workflows scene renders no cards)', async () => {
        silenceKeaLoadersErrors() // the 400 loader failure is the scenario under test
        // notConnected must react to any loader's 400, not cards alone — else the Workflows scene
        // could miss the connect prompt.
        mockWorkflowHealth.mockRejectedValue(new ApiError('Connect a GitHub data warehouse source.', 400))
        logic = engineeringAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowHealthFailure'])

        expect(logic.values.notConnected).toBe(true)
        expect(logic.values.workflowHealthLoadError).toBe(false)
    })

    it('a cards/PR 500 errors the PR scene only — not the Workflows scene', async () => {
        silenceKeaLoadersErrors() // the 500 loader failure is the scenario under test
        mockCiCards.mockRejectedValue(new ApiError('Internal Server Error', 500))
        logic = engineeringAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadCardsFailure'])

        expect(logic.values.pullRequestsLoadError).toBe(true)
        expect(logic.values.workflowHealthLoadError).toBe(false)
        expect(logic.values.notConnected).toBe(false)
    })

    it('a workflow-health 500 errors the Workflows scene only — not the PR scene', async () => {
        silenceKeaLoadersErrors() // the 500 loader failure is the scenario under test
        mockWorkflowHealth.mockRejectedValue(new ApiError('Internal Server Error', 500))
        logic = engineeringAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowHealthFailure'])

        expect(logic.values.workflowHealthLoadError).toBe(true)
        expect(logic.values.pullRequestsLoadError).toBe(false)
        expect(logic.values.notConnected).toBe(false)
    })

    it.each([
        ['all', { lifecycle: 'all' as const }, ['a-overdue', 'b-grace', 'c-soon', 'd-active', 'e-skip']],
        ['active', { lifecycle: 'active' as const }, ['d-active', 'e-skip']],
        ['expiring_soon', { lifecycle: 'expiring_soon' as const }, ['c-soon']],
        // past_expiry groups in_grace + overdue.
        ['past_expiry', { lifecycle: 'past_expiry' as const }, ['a-overdue', 'b-grace']],
        ['mode skip', { mode: 'skip' as const }, ['e-skip']],
        ['owner', { owner: '@team/x' }, ['a-overdue', 'c-soon']],
        ['search matches reason', { search: 'hang' }, ['e-skip']],
        ['search matches id', { search: 'b-grace' }, ['b-grace']],
    ])('filterQuarantineEntries: %s', (_label, partial, expectedIds) => {
        const rows = [
            qRow({ id: 'a-overdue', lifecycle: 'overdue', daysUntilExpiry: -10, owner: '@team/x' }),
            qRow({ id: 'b-grace', lifecycle: 'in_grace', daysUntilExpiry: -2, owner: '@team/y' }),
            qRow({ id: 'c-soon', lifecycle: 'expiring_soon', daysUntilExpiry: 3, owner: '@team/x' }),
            qRow({ id: 'd-active', lifecycle: 'active', daysUntilExpiry: 20, owner: '@team/z' }),
            qRow({ id: 'e-skip', lifecycle: 'active', mode: 'skip', owner: '@team/z', reason: 'teardown hang' }),
        ]
        const result = filterQuarantineEntries(rows, { ...DEFAULT_QUARANTINE_FILTERS, ...partial })
        expect(result.map((row) => row.id)).toEqual(expectedIds)
    })

    it('quarantineCountsOf tallies lifecycle buckets, past expiry, and skips', () => {
        const counts = quarantineCountsOf([
            qRow({ lifecycle: 'overdue' }),
            qRow({ lifecycle: 'in_grace' }),
            qRow({ lifecycle: 'expiring_soon' }),
            qRow({ lifecycle: 'active' }),
            qRow({ lifecycle: 'active', mode: 'skip' }),
        ])
        expect(counts).toEqual({
            active: 2,
            expiringSoon: 1,
            inGrace: 1,
            overdue: 1,
            pastExpiry: 2,
            skipped: 1,
            total: 5,
        })
    })

    it('maps the quarantine endpoint into rows with counts and owner options', async () => {
        logic = engineeringAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadQuarantineSuccess'])

        expect(logic.values.quarantine?.available).toBe(true)
        expect(logic.values.quarantine?.repoFullName).toBe('PostHog/posthog')
        expect(logic.values.quarantine?.entries).toHaveLength(5)
        expect(logic.values.quarantineCounts).toEqual({
            active: 2,
            expiringSoon: 1,
            inGrace: 1,
            overdue: 1,
            pastExpiry: 2,
            skipped: 1,
            total: 5,
        })
        expect(logic.values.quarantineOwnerOptions).toEqual(['@team/x', '@team/y', '@team/z'])
        expect(logic.values.quarantineLoadFailed).toBe(false)
    })

    it('quarantine cards toggle the lifecycle and mode lens and back', async () => {
        logic = engineeringAnalyticsLogic()
        logic.mount()
        expect(logic.values.activeQuarantineCard).toBeNull()

        logic.actions.applyQuarantineCard('past_expiry')
        expect(logic.values.activeQuarantineCard).toBe('past_expiry')
        expect(logic.values.quarantineLifecycleFilter).toBe('past_expiry')
        expect(logic.values.quarantineModeFilter).toBe('all')

        logic.actions.applyQuarantineCard('skipped')
        expect(logic.values.activeQuarantineCard).toBe('skipped')
        expect(logic.values.quarantineModeFilter).toBe('skip')
        expect(logic.values.quarantineLifecycleFilter).toBe('all')

        // Clicking the active card clears the lens back to the default view.
        logic.actions.applyQuarantineCard('skipped')
        expect(logic.values.activeQuarantineCard).toBeNull()
        expect(logic.values.quarantineModeFilter).toBe('all')
    })

    it('resetQuarantineFilters returns filters to defaults and clears hasActiveQuarantineFilters', async () => {
        logic = engineeringAnalyticsLogic()
        logic.mount()
        expect(logic.values.hasActiveQuarantineFilters).toBe(false)

        logic.actions.setQuarantineSearch('flake')
        logic.actions.setQuarantineLifecycleFilter('active')
        logic.actions.setQuarantineModeFilter('skip')
        logic.actions.setQuarantineOwner('@team/x')
        expect(logic.values.hasActiveQuarantineFilters).toBe(true)

        logic.actions.resetQuarantineFilters()
        expect(logic.values.quarantineFilters).toEqual(DEFAULT_QUARANTINE_FILTERS)
        expect(logic.values.hasActiveQuarantineFilters).toBe(false)
    })

    it('flags quarantineLoadFailed when the quarantine endpoint 400s', async () => {
        silenceKeaLoadersErrors() // the loader failure is the scenario under test
        mockQuarantine.mockRejectedValue(
            new Error('Connect a GitHub data warehouse source to use engineering analytics.')
        )

        logic = engineeringAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadQuarantineFailure'])

        expect(logic.values.quarantineLoadFailed).toBe(true)
    })

    it.each([
        ['product: selector', 'product:batch-exports', '@PostHog/team-batch-exports'],
        ['products/ path', 'products/web_analytics/backend/test_foo.py::T::t', '@PostHog/team-web-analytics'],
        ['plain nodeid', 'posthog/api/test/test_foo.py::T::t', ''],
        ['bare file', 'frontend/src/foo.test.ts', ''],
    ])('inferOwnerFromSelector: %s', (_label, selector, expected) => {
        expect(inferOwnerFromSelector(selector)).toBe(expected)
    })

    it.each([
        ['DRF detail', { detail: 'App not installed' }, 'App not installed'],
        ['nested data.detail', { data: { detail: 'Malformed file' } }, 'Malformed file'],
        ['error message', new Error('Network down'), 'Network down'],
        ['unknown shape', {}, 'Could not complete the quarantine request.'],
    ])('quarantineRequestErrorMessage: %s', (_label, error, expected) => {
        expect(quarantineRequestErrorMessage(error)).toBe(expected)
    })

    it('opens the quarantine modal with the given config', async () => {
        logic = engineeringAnalyticsLogic()
        logic.mount()

        logic.actions.openQuarantineModal({
            action: 'extend',
            selector: 'a/b.py::T::t',
            reason: 'flaky',
            owner: '@team/x',
            issue: 'https://github.com/PostHog/posthog/issues/7',
            mode: 'run',
        })
        expect(logic.values.quarantineModal?.action).toBe('extend')
        expect(logic.values.quarantineModal?.selector).toBe('a/b.py::T::t')

        logic.actions.closeQuarantineModal()
        expect(logic.values.quarantineModal).toBeNull()
    })

    it('a successful submit closes the modal and reloads the register', async () => {
        logic = engineeringAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadQuarantineSuccess'])

        logic.actions.openQuarantineModal({
            action: 'quarantine',
            selector: 'a/b.py::T::t',
            reason: 'flaky',
            owner: '@team/x',
            issue: '',
            mode: 'run',
        })
        logic.actions.submitQuarantine({
            input: {
                action: 'quarantine',
                selector: 'a/b.py::T::t',
                reason: 'flaky',
                owner: '@team/x',
                issue: '',
                expires: '2026-06-26',
                mode: 'run',
            },
        })
        // The success listener reloads the register so the merged change shows up.
        await expectLogic(logic).toDispatchActions(['submitQuarantineSuccess', 'loadQuarantine'])

        // The viewed repo is threaded into the write so the PR targets it.
        expect(mockQuarantineRequest).toHaveBeenCalledWith(
            '1',
            expect.objectContaining({ operation: 'quarantine', repo: 'PostHog/posthog' })
        )
        expect(logic.values.quarantineModal).toBeNull()
        expect(logic.values.quarantineSubmitLoading).toBe(false)
    })

    it('a failed submit keeps the modal open so the user can retry', async () => {
        silenceKeaLoadersErrors() // the submit failure is the scenario under test
        mockQuarantineRequest.mockRejectedValue({ detail: "The App isn't installed on PostHog." })
        logic = engineeringAnalyticsLogic()
        logic.mount()

        logic.actions.openQuarantineModal({
            action: 'quarantine',
            selector: 'a/b.py::T::t',
            reason: 'flaky',
            owner: '@team/x',
            issue: '',
            mode: 'run',
        })
        logic.actions.submitQuarantine({
            input: {
                action: 'quarantine',
                selector: 'a/b.py::T::t',
                reason: 'flaky',
                owner: '@team/x',
                issue: '',
                expires: null,
                mode: 'run',
            },
        })
        await expectLogic(logic).toDispatchActions(['submitQuarantineFailure'])

        expect(logic.values.quarantineModal).not.toBeNull()
        expect(logic.values.quarantineSubmitLoading).toBe(false)
    })
})
