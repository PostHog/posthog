import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { initKeaTests } from '~/test/init'

import {
    slackAppWorkspaceSetupChannelsRetrieve,
    slackAppWorkspaceSetupDefaultProjectCreate,
    slackAppWorkspaceSetupJoinChannelsCreate,
    slackAppWorkspaceSetupRetrieve,
} from '../generated/api'
import { slackAppWorkspaceSetupLogic } from './slackAppWorkspaceSetupLogic'

jest.mock('../generated/api', () => ({
    slackAppWorkspaceSetupRetrieve: jest.fn(),
    slackAppWorkspaceSetupDefaultProjectCreate: jest.fn(),
    slackAppWorkspaceSetupChannelsRetrieve: jest.fn(),
    slackAppWorkspaceSetupJoinChannelsCreate: jest.fn(),
}))

const mockRetrieve = slackAppWorkspaceSetupRetrieve as jest.Mock
const mockSaveDefaultProject = slackAppWorkspaceSetupDefaultProjectCreate as jest.Mock
const mockChannels = slackAppWorkspaceSetupChannelsRetrieve as jest.Mock
const mockJoinChannels = slackAppWorkspaceSetupJoinChannelsCreate as jest.Mock

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

    it('asks for the channels step on the Slack page, and reports the channels it could not join', async () => {
        mockRetrieve.mockResolvedValue({ ...BASE, project_options: [], steps: ['channels'] })
        mockChannels.mockResolvedValue({
            channels: [
                { id: 'C1', name: 'product', is_member: false },
                { id: 'C2', name: 'growth', is_member: false },
                { id: 'C3', name: 'general', is_member: true },
            ],
        })
        mockJoinChannels.mockResolvedValue({
            results: [
                { channel_id: 'C1', error: null },
                { channel_id: 'C2', error: 'is_archived' },
            ],
        })
        const warning = jest.spyOn(lemonToast, 'warning')

        const logic = slackAppWorkspaceSetupLogic({ integrationId: 7, entry: 'slack_page' })
        logic.mount()
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                currentStep: 'channels',
                joinedChannelNames: ['general'],
            })
        expect(mockRetrieve).toHaveBeenCalledWith(expect.any(String), '7', { entry: 'slack_page' })

        logic.actions.setSelectedChannelIds(['C1', 'C2'])
        await expectLogic(logic, () => logic.actions.joinChannels()).toFinishAllListeners()

        expect(mockJoinChannels).toHaveBeenCalledWith(expect.any(String), '7', {
            channel_ids: ['C1', 'C2'],
            post_welcome: false,
        })
        expect(warning).toHaveBeenCalledWith(expect.stringContaining('#growth'))
        await expectLogic(logic).toMatchValues({ currentStep: null })
    })
})
