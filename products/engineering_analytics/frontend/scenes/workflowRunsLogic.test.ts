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

    it('sends the shared run scope to every windowed read on the page, reloading all of them on a change', async () => {
        logic = workflowRunsLogic({ repoOwner: 'PostHog', repoName: 'posthog', workflowName: 'CI', sourceId: null })
        logic.mount()
        const filters = engineeringAnalyticsFiltersLogic()
        unmountFilters = filters.mount()
        const windowedReadSuccesses = [
            'loadRunsSuccess',
            'loadWorkflowHealthSuccess',
            'loadRunActivitySuccess',
            'loadRunnerCostsSuccess',
            'loadJobAggregatesSuccess',
        ]
        await expectLogic(logic).toDispatchActionsInAnyOrder(windowedReadSuccesses)

        const windowedReads = [mockRuns, mockWorkflowHealth, mockRunActivity, mockRunnerCosts, mockJobAggregates]
        for (const read of windowedReads) {
            expect(read).toHaveBeenLastCalledWith(
                '1',
                expect.objectContaining({ workflow_name: 'CI', repo: 'PostHog/posthog', date_from: '-7d' })
            )
            // All runs is the default, and the backend already reports every run when the param is absent.
            expect(read.mock.lastCall?.[1]).not.toHaveProperty('run_scope')
        }

        // Picking a group on the shared filters logic reloads all five reads scoped to it, so the detail
        // page's numbers and its chart match the list it was opened from.
        filters.actions.setRunScope('merge_queue')
        await expectLogic(logic).toDispatchActionsInAnyOrder(windowedReadSuccesses)
        for (const read of windowedReads) {
            expect(read).toHaveBeenLastCalledWith('1', expect.objectContaining({ run_scope: 'merge_queue' }))
        }
    })

    it('reads the tiles from the window-wide figures, not the capped run table', async () => {
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

        // A failed reload must not keep showing the previous window's 4000 runs under the fallback banner.
        mockWorkflowHealth.mockRejectedValue(new Error('network down'))
        const filters = engineeringAnalyticsFiltersLogic()
        unmountFilters = filters.mount()
        filters.actions.setDateRange('-7d', null)
        await expectLogic(logic).toDispatchActions(['loadWorkflowHealthFailure'])

        expect(logic.values.workflowHealthFailed).toBe(true)
        expect(logic.values.healthSummary.totalRuns).toBe(0)
        expect(logic.values.healthSummary.state).toBe('unknown')
    })
})
