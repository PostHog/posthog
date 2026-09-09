import { expectLogic } from 'kea-test-utils'

import { preflightLogic } from 'lib/logic/preflightLogic'
import { projectLogic } from 'scenes/projectLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { wizardRegistryList, wizardRunsCreate } from './generated/api'
import type { WizardProgramApi, WizardRunApi } from './generated/api.schemas'
import { wizardLibraryLogic } from './wizardLibraryLogic'
import { wizardRunDetailsLogic } from './wizardRunDetailsLogic'

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
        preflightLogic.actions.loadPreflightSuccess({ wizard_cloud_run_available: true } as any)
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('hides programs that only support local runs', () => {
        expect(logic.values.filteredPrograms).toEqual([program])
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

    it('runs the program version shown in the Library', async () => {
        logic.actions.openLibrary('stable-key')
        logic.actions.selectProgram(program)
        logic.actions.setRepository('posthog/posthog')

        logic.actions.createRun()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockWizardRunsCreate.mock.calls[0][1].wizard_version).toBe('2.67.0')
    })

    it('does not open the cloud-only Library when cloud runs are unavailable', async () => {
        preflightLogic.actions.loadPreflightSuccess({ wizard_cloud_run_available: false } as any)

        logic.actions.openLibrary('stable-key')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isLibraryOpen).toBe(false)
        expect(mockWizardRunsCreate).not.toHaveBeenCalled()
    })

    it('follows the new run after a successful start', async () => {
        const createdRun = { id: 'run-new' } as WizardRunApi
        mockWizardRunsCreate.mockResolvedValueOnce(createdRun)
        const detailsLogic = wizardRunDetailsLogic()
        detailsLogic.mount()
        logic.actions.openLibrary('stable-key')
        logic.actions.selectProgram(program)
        logic.actions.setRepository('posthog/posthog')

        logic.actions.createRun()
        await expectLogic(logic).toFinishAllListeners()

        expect(detailsLogic.values.selectedRunSummary?.id).toBe('run-new')
    })

    it('selects the retried program after the registry reloads', async () => {
        mockWizardRegistryList.mockResolvedValue({
            count: 2,
            next: null,
            previous: null,
            results: [program, localProgram],
        })
        const run = {
            id: 'run-old',
            program: { id: 'posthog-integration' },
            environment: 'cloud',
            workspace: { type: 'git_repository', repository: 'posthog/posthog' },
        }

        logic.actions.runAgain(run as any)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isLibraryOpen).toBe(true)
        expect(logic.values.selectedProgram?.id).toBe('posthog-integration')
    })

    it('marks the selection unavailable when the retried program is gone', async () => {
        mockWizardRegistryList.mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [localProgram],
        })
        const run = {
            id: 'run-old',
            program: { id: 'posthog-integration' },
            environment: 'cloud',
            workspace: { type: 'git_repository', repository: 'posthog/posthog' },
        }

        logic.actions.runAgain(run as any)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.selectedProgram).toBeNull()
        expect(logic.values.programSelectionInvalidated).toBe(true)
    })
})
