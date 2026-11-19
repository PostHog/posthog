import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'

import { initKeaTests } from '~/test/init'

import {
    engineeringAnalyticsRunFailureLogs,
    engineeringAnalyticsWorkflowJobs,
    engineeringAnalyticsWorkflowRun,
} from '../generated/api'
import type { WorkflowRunDetailApi } from '../generated/api.schemas'
import { workflowRunDetailLogic } from './workflowRunDetailLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsRunFailureLogs: jest.fn(),
    engineeringAnalyticsWorkflowJobs: jest.fn(),
    engineeringAnalyticsWorkflowRun: jest.fn(),
}))

const mockRun = engineeringAnalyticsWorkflowRun as jest.MockedFunction<typeof engineeringAnalyticsWorkflowRun>
const mockJobs = engineeringAnalyticsWorkflowJobs as jest.MockedFunction<typeof engineeringAnalyticsWorkflowJobs>
const mockLogs = engineeringAnalyticsRunFailureLogs as jest.MockedFunction<typeof engineeringAnalyticsRunFailureLogs>

const RUN: WorkflowRunDetailApi = {
    repo: { provider: 'github', owner: 'PostHog', name: 'posthog' },
    id: 42,
    workflow_name: 'CI',
    head_sha: 'abc123',
    head_branch: 'main',
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

describe('workflowRunDetailLogic', () => {
    let logic: ReturnType<typeof workflowRunDetailLogic.build>

    beforeEach(() => {
        initKeaTests()
        ApiConfig.setCurrentProjectId(1)
        jest.clearAllMocks()
        mockRun.mockResolvedValue(RUN)
        mockJobs.mockResolvedValue([])
    })

    afterEach(() => logic?.unmount())

    it('keeps colliding engine runs in separate logic instances and scopes all reads', async () => {
        const github = workflowRunDetailLogic({
            repoOwner: 'PostHog',
            repoName: 'posthog',
            runId: 42,
            ciEngine: 'github_actions',
            sourceId: null,
        })
        logic = workflowRunDetailLogic({
            repoOwner: 'PostHog',
            repoName: 'posthog',
            runId: 42,
            ciEngine: 'depot_ci',
            sourceId: null,
        })
        expect(logic).not.toBe(github)
        mockRun.mockResolvedValue({ ...RUN, conclusion: 'failure', ci_engine: 'depot_ci' })
        mockLogs.mockResolvedValue({
            run_id: 42,
            ci_engine: 'depot_ci',
            logs_available: false,
            jobs: [],
            truncated: false,
        })
        logic.mount()
        await expectLogic(logic).toDispatchActionsInAnyOrder([
            'loadRunSuccess',
            'loadJobsSuccess',
            'loadFailureLogsSuccess',
        ])
        for (const read of [mockRun, mockJobs, mockLogs]) {
            expect(read).toHaveBeenCalledWith('1', expect.objectContaining({ run_id: 42, ci_engine: 'depot_ci' }))
        }
    })
})
