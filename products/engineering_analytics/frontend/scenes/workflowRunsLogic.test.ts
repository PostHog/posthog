import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'

import { initKeaTests } from '~/test/init'

import {
    engineeringAnalyticsJobAggregates,
    engineeringAnalyticsWorkflowHealth,
    engineeringAnalyticsWorkflowJobs,
    engineeringAnalyticsWorkflowRunActivity,
    engineeringAnalyticsWorkflowRunnerCosts,
    engineeringAnalyticsWorkflowRuns,
} from '../generated/api'
import { engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'
import { workflowRunsLogic } from './workflowRunsLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsJobAggregates: jest.fn(),
    engineeringAnalyticsWorkflowHealth: jest.fn(),
    engineeringAnalyticsWorkflowJobs: jest.fn(),
    engineeringAnalyticsWorkflowRunActivity: jest.fn(),
    engineeringAnalyticsWorkflowRunnerCosts: jest.fn(),
    engineeringAnalyticsWorkflowRuns: jest.fn(),
}))

const mockRuns = engineeringAnalyticsWorkflowRuns as jest.MockedFunction<typeof engineeringAnalyticsWorkflowRuns>
const mockRunActivity = engineeringAnalyticsWorkflowRunActivity as jest.MockedFunction<
    typeof engineeringAnalyticsWorkflowRunActivity
>
const mockRunnerCosts = engineeringAnalyticsWorkflowRunnerCosts as jest.MockedFunction<
    typeof engineeringAnalyticsWorkflowRunnerCosts
>
const mockJobs = engineeringAnalyticsWorkflowJobs as jest.MockedFunction<typeof engineeringAnalyticsWorkflowJobs>
const mockJobAggregates = engineeringAnalyticsJobAggregates as jest.MockedFunction<
    typeof engineeringAnalyticsJobAggregates
>
const mockWorkflowHealth = engineeringAnalyticsWorkflowHealth as jest.MockedFunction<
    typeof engineeringAnalyticsWorkflowHealth
>

describe('workflowRunsLogic', () => {
    let logic: ReturnType<typeof workflowRunsLogic.build>

    beforeEach(() => {
        initKeaTests()
        ApiConfig.setCurrentProjectId(1)
        jest.clearAllMocks()
        mockRuns.mockResolvedValue([])
        mockRunActivity.mockResolvedValue({ points: [], truncated: false, limit: 0 })
        mockRunnerCosts.mockResolvedValue([])
        mockJobs.mockResolvedValue([])
        mockJobAggregates.mockResolvedValue([])
        mockWorkflowHealth.mockResolvedValue([])
    })

    let unmountFilters: (() => void) | undefined

    afterEach(() => {
        unmountFilters?.()
        unmountFilters = undefined
        logic?.unmount()
    })

    it('scopes the runs list, activity chart, and cost breakdown to the shared branch, reloading all on a change', async () => {
        logic = workflowRunsLogic({ repoOwner: 'PostHog', repoName: 'posthog', workflowName: 'CI', sourceId: null })
        logic.mount()
        const filters = engineeringAnalyticsFiltersLogic()
        unmountFilters = filters.mount()
        await expectLogic(logic).toDispatchActions([
            'loadRunsSuccess',
            'loadWorkflowHealthSuccess',
            'loadRunActivitySuccess',
            'loadRunnerCostsSuccess',
        ])

        // No branch applied → the endpoints see every branch (the pre-fix behavior for the whole page).
        const runsArgs = { workflow_name: 'CI', repo: 'PostHog/posthog', date_from: '-7d', branch: undefined }
        expect(mockRuns).toHaveBeenLastCalledWith('1', expect.objectContaining(runsArgs))
        expect(mockRunActivity).toHaveBeenLastCalledWith('1', expect.objectContaining(runsArgs))
        expect(mockRunnerCosts).toHaveBeenLastCalledWith('1', expect.objectContaining(runsArgs))
        // The tiles read this endpoint rather than folding the capped run table, so it carries the
        // same workflow, window and branch as the rest of the page.
        expect(mockWorkflowHealth).toHaveBeenLastCalledWith('1', expect.objectContaining(runsArgs))

        // Applying a branch on the shared filters logic reloads all three reads scoped to it — so the detail
        // page's numbers (and the chart's runs) match the branch-scoped Workflows tab instead of widening
        // back to all branches.
        filters.actions.setBranchFilter('master')
        filters.actions.applyBranchFilter()
        await expectLogic(logic).toDispatchActions([
            'loadRuns',
            'loadWorkflowHealth',
            'loadRunActivity',
            'loadRunnerCosts',
            'loadRunsSuccess',
            'loadWorkflowHealthSuccess',
            'loadRunActivitySuccess',
            'loadRunnerCostsSuccess',
        ])
        expect(mockRuns).toHaveBeenLastCalledWith('1', expect.objectContaining({ branch: 'master' }))
        expect(mockRunActivity).toHaveBeenLastCalledWith('1', expect.objectContaining({ branch: 'master' }))
        expect(mockRunnerCosts).toHaveBeenLastCalledWith('1', expect.objectContaining({ branch: 'master' }))
        expect(mockWorkflowHealth).toHaveBeenLastCalledWith('1', expect.objectContaining({ branch: 'master' }))
    })

    it('reads the tiles from the window-wide figures, not the capped run table', async () => {
        // 3800 of 3900 conclusive runs passed across the window; the run table only ever holds a page
        // of that, so folding the tiles off the table answered a narrower question than the Workflows
        // table did for the same workflow and window.
        mockWorkflowHealth.mockResolvedValue([
            {
                repo: { provider: 'github', owner: 'PostHog', name: 'posthog' },
                workflow_name: 'CI',
                run_count: 4000,
                successful_run_count: 3800,
                conclusive_run_count: 3900,
                success_rate: 0.974,
                p50_seconds: 120,
                p95_seconds: 600,
                last_failure_at: null,
                latest_run_failed: false,
                latest_run_conclusion: 'success',
                latest_run_id: 1,
                latest_run_attempt: 1,
                granularity: 'day',
                buckets: [],
            },
        ])
        logic = workflowRunsLogic({ repoOwner: 'PostHog', repoName: 'posthog', workflowName: 'CI', sourceId: null })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowHealthSuccess'])

        expect(logic.values.healthSummary.totalRuns).toBe(4000)
        expect(logic.values.healthSummary.passRate).toBe(0.974)
        expect(logic.values.healthSummary.state).toBe('healthy')
    })
})
