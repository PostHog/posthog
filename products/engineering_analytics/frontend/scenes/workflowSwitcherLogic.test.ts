import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'

import { initKeaTests } from '~/test/init'

import { engineeringAnalyticsWorkflowHealth } from '../generated/api'
import type { WorkflowHealthItemApi } from '../generated/api.schemas'
import { workflowSwitcherLogic } from './workflowSwitcherLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsWorkflowHealth: jest.fn(),
}))

const mockWorkflowHealth = engineeringAnalyticsWorkflowHealth as jest.MockedFunction<
    typeof engineeringAnalyticsWorkflowHealth
>

function healthItem(owner: string, name: string, workflowName: string): WorkflowHealthItemApi {
    return {
        repo: { provider: 'github', owner, name },
        workflow_name: workflowName,
    } as WorkflowHealthItemApi
}

describe('workflowSwitcherLogic', () => {
    let logic: ReturnType<typeof workflowSwitcherLogic.build>

    beforeEach(() => {
        initKeaTests()
        ApiConfig.setCurrentProjectId(1)
        jest.clearAllMocks()
        mockWorkflowHealth.mockResolvedValue([
            healthItem('PostHog', 'posthog', 'Frontend CI'),
            healthItem('PostHog', 'posthog', 'Backend CI'),
            healthItem('PostHog', 'posthog.com', 'Deploy'),
        ])
        logic = workflowSwitcherLogic({ repoOwner: 'PostHog', repoName: 'posthog', sourceId: null })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads lazily on first open only, keeping just the workflows of the scoped repo', async () => {
        // Mounting alone must not fetch — detail pages shouldn't pay for the list until the dropdown opens.
        expect(mockWorkflowHealth).not.toHaveBeenCalled()

        logic.actions.ensureWorkflowsLoaded()
        await expectLogic(logic).toDispatchActions(['loadWorkflowNamesSuccess'])
        expect(logic.values.workflowNames).toEqual(['Frontend CI', 'Backend CI'])

        // Re-opening the dropdown reuses the loaded list.
        logic.actions.ensureWorkflowsLoaded()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockWorkflowHealth).toHaveBeenCalledTimes(1)
    })
})
