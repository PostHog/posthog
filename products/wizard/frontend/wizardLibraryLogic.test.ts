import { expectLogic } from 'kea-test-utils'

import { projectLogic } from 'scenes/projectLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { wizardRegistryList, wizardRunsCreate } from './generated/api'
import type { WizardProgramApi } from './generated/api.schemas'
import { wizardLibraryLogic } from './wizardLibraryLogic'

jest.mock('./generated/api', () => ({
    wizardRegistryList: jest.fn(),
    wizardRunsCreate: jest.fn(),
    wizardRunsList: jest.fn().mockResolvedValue({ count: 0, next: null, previous: null, results: [] }),
}))

const mockWizardRegistryList = wizardRegistryList as jest.Mock
const mockWizardRunsCreate = wizardRunsCreate as jest.Mock

const program: WizardProgramApi = {
    id: 'posthog-integration',
    name: 'PostHog integration',
    description: 'Set up PostHog',
    wizard_version: '2.67.0',
    command: [],
    tags: [],
    required_programs: [],
    supported_environments: ['local', 'cloud'],
}

describe('wizardLibraryLogic', () => {
    let logic: ReturnType<typeof wizardLibraryLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/': () => [200, { results: [] }],
            },
        })
        jest.spyOn(console, 'error').mockImplementation()
        initKeaTests()
        mockWizardRegistryList.mockResolvedValue({ count: 1, next: null, previous: null, results: [program] })
        mockWizardRunsCreate.mockReset()
        await expectLogic(projectLogic).toMatchValues({ currentProjectId: expect.any(Number) })
        logic = wizardLibraryLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('reuses the idempotency key after a failed cloud request', async () => {
        mockWizardRunsCreate.mockRejectedValue(new Error('request failed'))
        logic.actions.openLibrary('stable-key')
        logic.actions.selectProgram(program)
        logic.actions.setRepository('posthog/posthog')

        logic.actions.createRun()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.createRun()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockWizardRunsCreate).toHaveBeenCalledTimes(2)
        expect(mockWizardRunsCreate.mock.calls[0][1].idempotency_key).toBe('stable-key')
        expect(mockWizardRunsCreate.mock.calls[1][1].idempotency_key).toBe('stable-key')
    })

    it('does not create a server run for local execution', async () => {
        logic.actions.openLibrary('stable-key')
        logic.actions.selectProgram(program)
        logic.actions.setLibraryEnvironment('local')

        logic.actions.createRun()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockWizardRunsCreate).not.toHaveBeenCalled()
    })
})
