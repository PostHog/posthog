import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'

import { initKeaTests } from '~/test/init'

import {
    engineeringAnalyticsCiDataFreshness,
    engineeringAnalyticsCiTimingContext,
    engineeringAnalyticsPrLifecycle,
    engineeringAnalyticsPrRuns,
    engineeringAnalyticsWorkflowJobs,
} from '../generated/api'
import type { CITimingContextApi, WorkflowJobApi, WorkflowRunDetailApi } from '../generated/api.schemas'
import { ciExplorerContextLogic } from './ciExplorerContextLogic'
import { ciExplorerLogic } from './ciExplorerLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsCiDataFreshness: jest.fn(),
    engineeringAnalyticsCiFailureLogs: jest.fn(),
    engineeringAnalyticsCiTimingContext: jest.fn(),
    engineeringAnalyticsJobLogInsights: jest.fn(),
    engineeringAnalyticsPrLifecycle: jest.fn(),
    engineeringAnalyticsPrRuns: jest.fn(),
    engineeringAnalyticsWorkflowJobs: jest.fn(),
}))
jest.mock('lib/elk', () => ({
    getElk: async () => ({ layout: async (graph: unknown) => graph }),
}))

const mockContext = engineeringAnalyticsCiTimingContext as jest.MockedFunction<
    typeof engineeringAnalyticsCiTimingContext
>
const mockRuns = engineeringAnalyticsPrRuns as jest.MockedFunction<typeof engineeringAnalyticsPrRuns>
const mockJobs = engineeringAnalyticsWorkflowJobs as jest.MockedFunction<typeof engineeringAnalyticsWorkflowJobs>

const PROPS = { repoOwner: 'PostHog', repoName: 'posthog', number: 10, sourceId: null }
const WORKFLOW = 'github_actions:42:1'
const LINT = `${WORKFLOW}/Lint`
const BUILD = `${WORKFLOW}/Build`

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

function job(id: number, name: string): WorkflowJobApi {
    return {
        id,
        run_id: 42,
        name,
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
}

function answer(averageSeconds: number): CITimingContextApi {
    return {
        default_branch: 'master',
        window_days: 7,
        identity: 'workflow_id',
        runs_scanned: 12,
        sampled: false,
        sample_count: 9,
        average_seconds: averageSeconds,
        recent: [],
        runs_synced_at: '2026-06-01T00:10:00Z',
        jobs_synced_at: '2026-06-01T00:10:00Z',
        unavailable_reason: null,
    }
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve: (value: T) => void = () => {}
    const promise = new Promise<T>((r) => (resolve = r))
    return { promise, resolve }
}

describe('ciExplorerContextLogic', () => {
    let explorer: ReturnType<typeof ciExplorerLogic.build>
    let logic: ReturnType<typeof ciExplorerContextLogic.build>

    beforeEach(async () => {
        localStorage.clear()
        initKeaTests()
        ApiConfig.setCurrentProjectId(1)
        jest.clearAllMocks()
        ;(engineeringAnalyticsPrLifecycle as jest.Mock).mockResolvedValue(null)
        ;(engineeringAnalyticsCiDataFreshness as jest.Mock).mockResolvedValue(null)
        mockRuns.mockResolvedValue([RUN])
        mockJobs.mockResolvedValue([job(1, 'Lint'), job(2, 'Build')])
        explorer = ciExplorerLogic(PROPS)
        explorer.mount()
        logic = ciExplorerContextLogic(PROPS)
        logic.mount()
        await expectLogic(explorer).toDispatchActions(['loadLayoutsSuccess'])
    })

    afterEach(() => {
        logic?.unmount()
        explorer?.unmount()
    })

    it('asks for nothing until the Context tab is open', async () => {
        explorer.actions.setFocus(LINT)
        explorer.actions.openDrawer('details')
        explorer.actions.setFocus(BUILD)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockContext).not.toHaveBeenCalled()

        mockContext.mockResolvedValue(answer(100))
        explorer.actions.openDrawer('context')
        await expectLogic(logic).toDispatchActions(['loadAnswerSuccess'])

        expect(mockContext).toHaveBeenCalledTimes(1)
        expect(mockContext.mock.calls[0][1]).toMatchObject({ kind: 'job', job_ids: '2', run_id: 42, run_attempt: 1 })
    })

    it('cancels the request for a selection the person left, and never shows its late answer', async () => {
        const first = deferred<CITimingContextApi>()
        const second = deferred<CITimingContextApi>()
        mockContext.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)

        // The logic waits for the selection to settle before it asks, so the test owns that clock.
        jest.useFakeTimers()
        try {
            explorer.actions.setFocus(LINT)
            explorer.actions.openDrawer('context')
            await jest.advanceTimersByTimeAsync(1000)
            explorer.actions.setFocus(BUILD)
            await jest.advanceTimersByTimeAsync(1000)

            expect(mockContext).toHaveBeenCalledTimes(2)
            expect((mockContext.mock.calls[0][2] as RequestInit).signal?.aborted).toBe(true)
            expect((mockContext.mock.calls[1][2] as RequestInit).signal?.aborted).toBe(false)

            first.resolve(answer(1))
            await jest.advanceTimersByTimeAsync(0)
            expect(logic.values.context).toBeNull()

            second.resolve(answer(100))
            await jest.advanceTimersByTimeAsync(0)
            expect(logic.values.context).toMatchObject({ average_seconds: 100 })
        } finally {
            jest.useRealTimers()
        }
    })

    it('reports a failed request and asks again on retry', async () => {
        mockContext.mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce(answer(100))

        explorer.actions.setFocus(LINT)
        explorer.actions.openDrawer('context')
        await expectLogic(logic).toDispatchActions(['loadAnswerFailure'])
        expect(logic.values).toMatchObject({ failed: true, context: null })

        logic.actions.retry()
        await expectLogic(logic).toDispatchActions(['loadAnswerSuccess'])
        expect(logic.values).toMatchObject({ failed: false, context: { average_seconds: 100 } })
    })
})
