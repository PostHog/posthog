import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiConfig } from 'lib/api'

import { initKeaTests } from '~/test/init'

import {
    engineeringAnalyticsCiDataFreshness,
    engineeringAnalyticsJobLogInsights,
    engineeringAnalyticsPrLifecycle,
    engineeringAnalyticsPrRuns,
    engineeringAnalyticsWorkflowJobs,
} from '../generated/api'
import type { WorkflowJobApi, WorkflowRunDetailApi } from '../generated/api.schemas'
import { ciExplorerLogic } from './ciExplorerLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsCiDataFreshness: jest.fn(),
    engineeringAnalyticsCiFailureLogs: jest.fn(),
    engineeringAnalyticsJobLogInsights: jest.fn(),
    engineeringAnalyticsPrLifecycle: jest.fn(),
    engineeringAnalyticsPrRuns: jest.fn(),
    engineeringAnalyticsWorkflowJobs: jest.fn(),
}))
jest.mock('lib/elk', () => ({
    getElk: async () => ({ layout: async (graph: unknown) => graph }),
}))

const mockInsights = engineeringAnalyticsJobLogInsights as jest.MockedFunction<
    typeof engineeringAnalyticsJobLogInsights
>

const PROPS = { repoOwner: 'PostHog', repoName: 'posthog', number: 10, sourceId: null }
const PAGE = '/engineering-analytics/repos/PostHog/posthog/pull-requests/10/ci-explorer'
const LINT = 'github_actions:42:1/Lint'

const RUN: WorkflowRunDetailApi = {
    repo: { provider: 'github', owner: 'PostHog', name: 'posthog' },
    id: 42,
    workflow_name: 'CI',
    workflow_id: 7,
    ci_engine: 'github_actions',
    head_sha: 'abc123',
    head_branch: 'feature',
    status: 'completed',
    conclusion: 'success',
    run_started_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:05:00Z',
    duration_seconds: 300,
    run_attempt: 1,
    pr_number: 10,
    commit_pr_number: null,
    is_merge_queue: false,
}

const LINT_JOB: WorkflowJobApi = {
    id: 1,
    run_id: 42,
    name: 'Lint',
    status: 'completed',
    conclusion: 'success',
    started_at: '2026-06-01T00:00:00Z',
    completed_at: '2026-06-01T00:02:00Z',
    duration_seconds: 120,
    runner_provider: 'self_hosted',
    runner_label: 'depot-ubuntu-latest',
    estimated_cost_usd: null,
    ci_engine: 'github_actions',
    steps: [],
}

describe('ciExplorerLogic', () => {
    let logic: ReturnType<typeof ciExplorerLogic.build>
    let capture: jest.SpyInstance

    const open = (search: string): void => {
        router.actions.push(`${PAGE}${search}`)
        logic = ciExplorerLogic(PROPS)
        logic.mount()
    }
    const viewedEvents = (): unknown[] =>
        capture.mock.calls.filter(([event]) => event === 'ci explorer viewed').map(([, properties]) => properties)

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        ApiConfig.setCurrentProjectId(1)
        jest.clearAllMocks()
        capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        ;(engineeringAnalyticsPrLifecycle as jest.Mock).mockResolvedValue(null)
        ;(engineeringAnalyticsCiDataFreshness as jest.Mock).mockResolvedValue(null)
        ;(engineeringAnalyticsPrRuns as jest.Mock).mockResolvedValue([RUN])
        ;(engineeringAnalyticsWorkflowJobs as jest.Mock).mockResolvedValue([LINT_JOB])
        mockInsights.mockResolvedValue({
            log_read: true,
            attributed_to_steps: true,
            job: [],
            steps: [],
            log_truncated: false,
        })
    })

    afterEach(() => {
        logic?.unmount()
        capture.mockRestore()
    })

    test.each([
        ['the plain page', '', { view: 'overview', older_commit: false }],
        ['a link to a view', '?view=activity', { view: 'activity', older_commit: false }],
        ['a link to a commit', '?sha=def456', { view: 'overview', older_commit: true }],
    ])('captures one viewed event when %s opens', (_, search, properties) => {
        open(search)

        expect(viewedEvents()).toEqual([properties])
    })

    it('captures a viewed event when the view changes without a link', () => {
        open('')
        logic.actions.setView('activity')

        expect(viewedEvents()).toEqual([
            { view: 'overview', older_commit: false },
            { view: 'activity', older_commit: false },
        ])
    })

    it('reads the log of a job that a link focused before the jobs arrived', async () => {
        open(`?node=${encodeURIComponent(LINT)}`)
        await expectLogic(logic).toDispatchActions(['loadJobInsightsSuccess'])

        expect(mockInsights).toHaveBeenCalledTimes(1)
        expect(mockInsights.mock.calls[0][1]).toMatchObject({ run_id: 42, job_id: 1 })
    })
})
