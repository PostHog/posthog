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

    afterEach(() => {
        logic?.unmount()
    })

    it('scopes the runs list, activity chart, and cost breakdown to the shared branch, reloading all on a change', async () => {
        logic = workflowRunsLogic({ repoOwner: 'PostHog', repoName: 'posthog', workflowName: 'CI', sourceId: null })
        logic.mount()
        const filters = engineeringAnalyticsFiltersLogic()
        filters.mount()
        await expectLogic(logic).toDispatchActions([
            'loadRunsSuccess',
            'loadRunActivitySuccess',
            'loadRunnerCostsSuccess',
        ])

        // No branch applied → the endpoints see every branch (the pre-fix behavior for the whole page).
        const runsArgs = { workflow_name: 'CI', repo: 'PostHog/posthog', date_from: '-7d', branch: undefined }
        // Third arg carries the unmount abort signal so in-flight loaders cancel on navigate-away.
        const withSignal = expect.objectContaining({ signal: expect.anything() })
        expect(mockRuns).toHaveBeenLastCalledWith('1', expect.objectContaining(runsArgs), withSignal)
        expect(mockRunActivity).toHaveBeenLastCalledWith('1', expect.objectContaining(runsArgs), withSignal)
        expect(mockRunnerCosts).toHaveBeenLastCalledWith('1', expect.objectContaining(runsArgs), withSignal)

        // Applying a branch on the shared filters logic reloads all three reads scoped to it — so the detail
        // page's numbers (and the chart's runs) match the branch-scoped Workflows tab instead of widening
        // back to all branches.
        filters.actions.setBranchFilter('master')
        filters.actions.applyBranchFilter()
        await expectLogic(logic).toDispatchActions([
            'loadRuns',
            'loadRunActivity',
            'loadRunnerCosts',
            'loadRunsSuccess',
            'loadRunActivitySuccess',
            'loadRunnerCostsSuccess',
        ])
        expect(mockRuns).toHaveBeenLastCalledWith('1', expect.objectContaining({ branch: 'master' }), withSignal)
        expect(mockRunActivity).toHaveBeenLastCalledWith('1', expect.objectContaining({ branch: 'master' }), withSignal)
        expect(mockRunnerCosts).toHaveBeenLastCalledWith('1', expect.objectContaining({ branch: 'master' }), withSignal)
    })

    it('swallows a transient network failure instead of surfacing it as a load failure', async () => {
        // A network blip rejects `fetch` with a `TypeError` that `handleFetch` rewraps as an error whose
        // message still reads "Failed to fetch" and which carries no HTTP status. Without the guard this
        // flips to a `*Failure` action and lands in error tracking; the loader must treat it as non-fatal.
        mockJobAggregates.mockRejectedValueOnce(new TypeError('Failed to fetch'))

        logic = workflowRunsLogic({ repoOwner: 'PostHog', repoName: 'posthog', workflowName: 'CI', sourceId: null })
        logic.mount()
        engineeringAnalyticsFiltersLogic().mount()

        await expectLogic(logic)
            .toDispatchActions(['loadJobAggregates', 'loadJobAggregatesSuccess'])
            .toNotHaveDispatchedActions(['loadJobAggregatesFailure'])
        expect(logic.values.jobAggregates).toEqual([])
    })
})
