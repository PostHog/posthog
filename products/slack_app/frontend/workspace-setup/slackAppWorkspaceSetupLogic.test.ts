import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { slackAppWorkspaceSetupDefaultProjectCreate, slackAppWorkspaceSetupRetrieve } from '../generated/api'
import { slackAppWorkspaceSetupLogic } from './slackAppWorkspaceSetupLogic'

jest.mock('../generated/api', () => ({
    slackAppWorkspaceSetupRetrieve: jest.fn(),
    slackAppWorkspaceSetupDefaultProjectCreate: jest.fn(),
}))

const mockRetrieve = slackAppWorkspaceSetupRetrieve as jest.Mock
const mockSaveDefaultProject = slackAppWorkspaceSetupDefaultProjectCreate as jest.Mock

const BASE = {
    integration_id: 7,
    slack_workspace_name: 'Hedgebox',
    open_slack_url: 'https://slack.com/app_redirect?app=A1&team=T1',
    project_options: [
        { integration_id: 7, project_name: 'Hedgebox web', organization_name: 'Hedgebox' },
        { integration_id: 8, project_name: 'Hedgebox mobile', organization_name: 'Hedgebox' },
    ],
}

describe('slackAppWorkspaceSetupLogic', () => {
    beforeEach(() => {
        initKeaTests()
        mockRetrieve.mockResolvedValue({
            ...BASE,
            steps: ['ai_consent', 'a_step_this_frontend_does_not_know', 'default_project'],
        })
        mockSaveDefaultProject.mockResolvedValue({ ...BASE, steps: [], project_options: [] })
    })

    it('walks the known steps, saves the picked project, and keeps the step count after the save', async () => {
        const logic = slackAppWorkspaceSetupLogic({ integrationId: 7 })
        logic.mount()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                steps: ['ai_consent', 'default_project'],
                currentStep: 'ai_consent',
                currentStepNumber: 1,
            })

        logic.actions.skipStep('ai_consent')
        logic.actions.selectProject(8)
        await expectLogic(logic).toMatchValues({ currentStep: 'default_project', currentStepNumber: 2 })

        await expectLogic(logic, () => logic.actions.saveDefaultProject()).toFinishAllListeners()

        expect(mockSaveDefaultProject).toHaveBeenCalledWith(expect.any(String), '7', { integration_id: 8 })
        await expectLogic(logic).toMatchValues({
            currentStep: null,
            steps: ['ai_consent', 'default_project'],
            skippedSteps: ['ai_consent'],
        })
    })
})
