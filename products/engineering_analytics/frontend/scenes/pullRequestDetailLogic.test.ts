import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'

import { initKeaTests } from '~/test/init'

import { engineeringAnalyticsPrRuns, engineeringAnalyticsWorkflowJobs } from '../generated/api'
import type { CIEngineEnumApi, WorkflowJobApi, WorkflowRunDetailApi } from '../generated/api.schemas'
import { pullRequestDetailLogic } from './pullRequestDetailLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsPrLifecycle: jest.fn().mockResolvedValue(null),
    engineeringAnalyticsPrRuns: jest.fn(),
    engineeringAnalyticsPullRequestTimelines: jest.fn().mockResolvedValue(null),
    engineeringAnalyticsPrCost: jest.fn().mockResolvedValue(null),
    engineeringAnalyticsCiFailureLogs: jest.fn().mockResolvedValue(null),
    engineeringAnalyticsWorkflowJobs: jest.fn(),
}))

const mockRuns = engineeringAnalyticsPrRuns as jest.MockedFunction<typeof engineeringAnalyticsPrRuns>
const mockJobs = engineeringAnalyticsWorkflowJobs as jest.MockedFunction<typeof engineeringAnalyticsWorkflowJobs>

describe('pullRequestDetailLogic', () => {
    let logic: ReturnType<typeof pullRequestDetailLogic.build>

    beforeEach(() => {
        initKeaTests()
        ApiConfig.setCurrentProjectId(1)
        jest.clearAllMocks()
    })

    afterEach(() => logic?.unmount())

    it.each<CIEngineEnumApi>(['github_actions', 'depot_ci'])(
        'shows cached failure labels and avoids duplicate job reads for %s',
        async (ciEngine) => {
            const run: WorkflowRunDetailApi = {
                repo: { provider: 'github', owner: 'PostHog', name: 'posthog' },
                id: 42,
                ci_engine: ciEngine,
                workflow_name: 'CI',
                head_sha: 'abc123',
                head_branch: 'main',
                status: 'completed',
                conclusion: 'failure',
                run_started_at: '2026-06-01T00:00:00Z',
                updated_at: '2026-06-01T00:05:00Z',
                duration_seconds: 300,
                run_attempt: 1,
                pr_number: 10,
                commit_pr_number: null,
                is_merge_queue: false,
            }
            const job: WorkflowJobApi = {
                id: 7,
                run_id: 42,
                ci_engine: ciEngine,
                name: 'Python tests',
                status: 'completed',
                conclusion: 'failure',
                started_at: run.run_started_at,
                completed_at: run.updated_at,
                duration_seconds: 300,
                runner_provider: 'self_hosted',
                runner_label: '16-core',
                estimated_cost_usd: 1,
            }
            mockRuns.mockResolvedValue([run])
            mockJobs.mockResolvedValue([job])
            logic = pullRequestDetailLogic({
                repoOwner: 'PostHog',
                repoName: 'posthog',
                number: 10,
                sourceId: null,
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadJobsSuccess']).toFinishAllListeners()

            expect(logic.values.failingJobLabelByWorkflow).toEqual({ CI: 'Python tests' })
            expect(mockJobs).toHaveBeenCalledWith('1', expect.objectContaining({ run_id: 42, ci_engine: ciEngine }))

            await expectLogic(logic, () => logic.actions.loadPrRuns()).toFinishAllListeners()
            expect(mockJobs).toHaveBeenCalledTimes(1)
        }
    )
})
