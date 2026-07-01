import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'

import { initKeaTests } from '~/test/init'

import {
    engineeringAnalyticsWorkflowJobs,
    engineeringAnalyticsWorkflowRunnerCosts,
    engineeringAnalyticsWorkflowRuns,
} from '../generated/api'
import { engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'
import { workflowRunsLogic } from './workflowRunsLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsWorkflowJobs: jest.fn(),
    engineeringAnalyticsWorkflowRunnerCosts: jest.fn(),
    engineeringAnalyticsWorkflowRuns: jest.fn(),
}))

const mockRuns = engineeringAnalyticsWorkflowRuns as jest.MockedFunction<typeof engineeringAnalyticsWorkflowRuns>
const mockRunnerCosts = engineeringAnalyticsWorkflowRunnerCosts as jest.MockedFunction<
    typeof engineeringAnalyticsWorkflowRunnerCosts
>
const mockJobs = engineeringAnalyticsWorkflowJobs as jest.MockedFunction<typeof engineeringAnalyticsWorkflowJobs>

describe('workflowRunsLogic', () => {
    let logic: ReturnType<typeof workflowRunsLogic.build>

    beforeEach(() => {
        initKeaTests()
        ApiConfig.setCurrentProjectId(1)
        jest.clearAllMocks()
        mockRuns.mockResolvedValue([])
        mockRunnerCosts.mockResolvedValue([])
        mockJobs.mockResolvedValue([])
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('scopes the runs list and cost breakdown to the shared branch, reloading both on a change', async () => {
        logic = workflowRunsLogic({ repoOwner: 'PostHog', repoName: 'posthog', workflowName: 'CI', sourceId: null })
        logic.mount()
        const filters = engineeringAnalyticsFiltersLogic()
        filters.mount()
        await expectLogic(logic).toDispatchActions(['loadRunsSuccess', 'loadRunnerCostsSuccess'])

        // No branch applied → the endpoints see every branch (the pre-fix behavior for the whole page).
        const runsArgs = { workflow_name: 'CI', repo: 'PostHog/posthog', date_from: '-7d', branch: undefined }
        expect(mockRuns).toHaveBeenLastCalledWith('1', expect.objectContaining(runsArgs))
        expect(mockRunnerCosts).toHaveBeenLastCalledWith('1', expect.objectContaining(runsArgs))

        // Applying a branch on the shared filters logic reloads both lists scoped to it — so the detail
        // page's numbers match the branch-scoped Workflows tab instead of widening back to all branches.
        filters.actions.setBranchFilter('master')
        filters.actions.applyBranchFilter()
        await expectLogic(logic).toDispatchActions([
            'loadRuns',
            'loadRunnerCosts',
            'loadRunsSuccess',
            'loadRunnerCostsSuccess',
        ])
        expect(mockRuns).toHaveBeenLastCalledWith('1', expect.objectContaining({ branch: 'master' }))
        expect(mockRunnerCosts).toHaveBeenLastCalledWith('1', expect.objectContaining({ branch: 'master' }))
    })
})
