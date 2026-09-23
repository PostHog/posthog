import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { engineeringAnalyticsWorkflowJobs, engineeringAnalyticsWorkflowRun } from '../generated/api'
import type { WorkflowRunDetailApi } from '../generated/api.schemas'
import { workflowRunDetailLogic } from './workflowRunDetailLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsRunFailureLogs: jest.fn(),
    engineeringAnalyticsWorkflowJobs: jest.fn(),
    engineeringAnalyticsWorkflowRun: jest.fn(),
}))

const mockRun = engineeringAnalyticsWorkflowRun as jest.MockedFunction<typeof engineeringAnalyticsWorkflowRun>
const mockJobs = engineeringAnalyticsWorkflowJobs as jest.MockedFunction<typeof engineeringAnalyticsWorkflowJobs>

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

    it('links the loaded workflow breadcrumb back with the current scope', async () => {
        router.actions.push(urls.engineeringAnalyticsWorkflowRun('PostHog', 'posthog', 42), {
            source: 'source-1',
            repo: 'PostHog/posthog',
            date_from: '2026-06-01',
            date_to: '2026-06-30',
            run_scope: 'merge_queue',
        })
        logic = workflowRunDetailLogic({
            repoOwner: 'PostHog',
            repoName: 'posthog',
            runId: 42,
            sourceId: 'source-1',
        })
        logic.mount()

        await expectLogic(logic).toDispatchActionsInAnyOrder(['loadRunSuccess', 'loadJobsSuccess'])

        expect(logic.values.breadcrumbs.map(({ name }) => name)).toEqual([
            'Engineering analytics',
            'Workflows',
            'PostHog/posthog · CI',
            'run #42',
        ])
        const workflowDestination = new URL(logic.values.breadcrumbs[2].path!, 'https://example.com')
        expect(workflowDestination.pathname).toBe(
            new URL(urls.engineeringAnalyticsWorkflowRuns('PostHog', 'posthog', 'CI'), 'https://example.com').pathname
        )
        expect(Object.fromEntries(workflowDestination.searchParams)).toEqual({
            date_from: '2026-06-01',
            date_to: '2026-06-30',
            run_scope: 'merge_queue',
            source: 'source-1',
            repo: 'PostHog/posthog',
        })

        router.actions.replace(urls.engineeringAnalyticsWorkflowRun('PostHog', 'posthog', 42), {
            source: 'source-1',
            repo: 'PostHog/posthog',
            date_from: '-30d',
        })
        const hubDestination = new URL(logic.values.breadcrumbs[0].path!, 'https://example.com')
        expect(Object.fromEntries(hubDestination.searchParams)).toEqual({
            date_from: '-30d',
            source: 'source-1',
            repo: 'PostHog/posthog',
        })
    })
})
