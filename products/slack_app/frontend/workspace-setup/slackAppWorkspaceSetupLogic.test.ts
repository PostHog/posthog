import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { slackAppWorkspaceSetupRetrieve } from '../generated/api'
import { slackAppWorkspaceSetupLogic } from './slackAppWorkspaceSetupLogic'

jest.mock('../generated/api', () => ({ slackAppWorkspaceSetupRetrieve: jest.fn() }))
jest.mock('./workspaceSetupSteps', () => ({
    WORKSPACE_SETUP_STEPS: { first: () => null, second: () => null },
}))

const mockRetrieve = slackAppWorkspaceSetupRetrieve as jest.Mock

describe('slackAppWorkspaceSetupLogic', () => {
    beforeEach(() => {
        initKeaTests()
        mockRetrieve.mockResolvedValue({
            integration_id: 7,
            slack_workspace_name: 'Hedgebox',
            open_slack_url: 'https://slack.com/app_redirect?app=A1&team=T1',
            steps: ['first', 'step_this_frontend_does_not_know', 'second'],
        })
    })

    it('leaves out unknown steps and moves to the done screen after the last step', async () => {
        const logic = slackAppWorkspaceSetupLogic({ integrationId: 7 })
        logic.mount()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ steps: ['first', 'second'], currentStep: 'first', currentStepNumber: 1 })

        logic.actions.skipStep('first')
        await expectLogic(logic).toMatchValues({ currentStep: 'second', currentStepNumber: 2 })

        logic.actions.completeStep('second')
        await expectLogic(logic).toMatchValues({ currentStep: null })
    })
})
