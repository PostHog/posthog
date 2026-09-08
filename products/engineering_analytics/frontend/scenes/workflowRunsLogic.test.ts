import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'

import { initKeaTests } from '~/test/init'

import {
    engineeringAnalyticsJobAggregates,
    engineeringAnalyticsWorkflowJobs,
    engineeringAnalyticsWorkflowRunActivity,
    engineeringAnalyticsWorkflowRunnerCosts,
    engineeringAnalyticsWorkflowRuns,
} from '../generated/api'
import { engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'
import { workflowRunsLogic } from './workflowRunsLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsJobAggregates: jest.fn(),
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
        await expectLogic(logic).toDispatchActions([
            'loadRunsSuccess',
            'loadRunActivitySuccess',
            'loadRunnerCostsSuccess',
            'loadJobAggregatesSuccess',
        ])

        const windowedReads = [mockRuns, mockRunActivity, mockRunnerCosts, mockJobAggregates]
        for (const read of windowedReads) {
            expect(read).toHaveBeenLastCalledWith(
                '1',
                expect.objectContaining({ workflow_name: 'CI', repo: 'PostHog/posthog', date_from: '-7d' })
            )
            // All runs is the default, and the backend already reports every run when the param is absent.
            expect(read.mock.lastCall?.[1]).not.toHaveProperty('run_scope')
        }

        // Picking a group on the shared filters logic reloads all four reads scoped to it, so the detail
        // page's numbers and its chart match the list it was opened from.
        filters.actions.setRunScope('merge_queue')
        await expectLogic(logic).toDispatchActions([
            'loadRuns',
            'loadRunActivity',
            'loadRunnerCosts',
            'loadJobAggregates',
            'loadRunsSuccess',
            'loadRunActivitySuccess',
            'loadRunnerCostsSuccess',
            'loadJobAggregatesSuccess',
        ])
        for (const read of windowedReads) {
            expect(read).toHaveBeenLastCalledWith('1', expect.objectContaining({ run_scope: 'merge_queue' }))
        }
    })
})
