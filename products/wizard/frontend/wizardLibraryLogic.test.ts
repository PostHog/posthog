import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { projectLogic } from 'scenes/projectLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { wizardRegistryList, wizardRunsCreate } from './generated/api'
import type { WizardProgramApi, WizardRunApi } from './generated/api.schemas'
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

const localProgram: WizardProgramApi = {
    ...program,
    id: 'local-program',
    name: 'Local program',
    supported_environments: ['local'],
}

const createdRun: WizardRunApi = {
    id: 'run-1',
    team_id: 1,
    created_by_id: 1,
    environment: 'cloud',
    workspace: { type: 'git_repository', repository: 'posthog/posthog' },
    program,
    status: 'created',
    error_code: null,
    error_message: null,
    stage: null,
    created_at: '2026-08-26T10:00:00Z',
    updated_at: '2026-08-26T10:00:00Z',
    started_at: null,
    finished_at: null,
    deadline_at: '2026-08-26T11:00:00Z',
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
        mockWizardRegistryList.mockResolvedValue({
            count: 2,
            next: null,
            previous: null,
            results: [program, localProgram],
        })
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

    it('hides programs that only support local runs', () => {
        expect(logic.values.filteredPrograms).toEqual([program])
    })

    it('reports a cloud run started from the launchpad', async () => {
        mockWizardRunsCreate.mockResolvedValue(createdRun)
        logic.actions.openLibrary('stable-key')
        logic.actions.selectProgram(program)
        logic.actions.setRepository('posthog/posthog')

        logic.actions.createRun()
        await expectLogic(logic).toFinishAllListeners()

        expect(posthog.capture).toHaveBeenCalledWith('wizard launchpad run started', {
            surface: 'cloud_launchpad',
            wizard_run_id: 'run-1',
            run_environment: 'cloud',
            program_id: 'posthog-integration',
            workspace_type: 'git_repository',
        })
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
