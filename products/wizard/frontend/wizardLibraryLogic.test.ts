import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { projectLogic } from 'scenes/projectLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { wizardRegistryList, wizardRunsCreate } from './generated/api'
import type { WizardProgramApi, WizardRunApi } from './generated/api.schemas'
import { wizardLibraryLogic } from './wizardLibraryLogic'
import { wizardRunDetailsLogic } from './wizardRunDetailsLogic'

jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn(),
}))

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
function makeRun(overrides: Partial<WizardRunApi> = {}): WizardRunApi {
    return {
        id: 'run-new',
        team_id: 1,
        created_by_id: 1,
        environment: 'cloud',
        workspace: { type: 'git_repository', repository: 'example/private-project' },
        program,
        status: 'created',
        error_code: null,
        error_message: null,
        stage: 'dispatching',
        created_at: '2026-08-26T10:00:00Z',
        updated_at: null,
        started_at: null,
        finished_at: null,
        deadline_at: null,
        ...overrides,
    }
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
        mockWizardRunsCreate.mockReset().mockResolvedValue(makeRun())
        jest.spyOn(posthog, 'capture').mockClear()
        jest.mocked(copyToClipboard).mockReset().mockResolvedValue(true)
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

    it.each([true, false])('tracks command copies only when the clipboard succeeds: %s', async (copied) => {
        jest.mocked(copyToClipboard).mockResolvedValue(copied)
        logic.actions.selectProgram(program)
        logic.actions.copyCommand()
        await expectLogic(logic).toFinishAllListeners()

        const events = jest.mocked(posthog.capture).mock.calls.filter(([event]) => event === 'wizard command copied')
        expect(events).toHaveLength(copied ? 1 : 0)
        if (copied) {
            expect(events[0][1]).toEqual(
                expect.objectContaining({
                    program_id: program.id,
                    version: '2.67.0',
                    run_surface: 'local',
                    command: 'default',
                })
            )
            expect(events[0][1]).not.toHaveProperty('task_run_id')
            expect(JSON.stringify(events)).not.toContain('npx')
        }
    })

    it('reuses the idempotency key after a failed cloud request', async () => {
        mockWizardRunsCreate.mockRejectedValue(new ApiError('private response content', 429))
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
        const events = jest
            .mocked(posthog.capture)
            .mock.calls.filter(([event]) => event.startsWith('wizard run create'))
        expect(events.map(([event]) => event)).toEqual([
            'wizard run create requested',
            'wizard run create failed',
            'wizard run create requested',
            'wizard run create failed',
        ])
        expect(events[1][1]).toEqual(
            expect.objectContaining({ http_status: 429, run_surface: 'cloud', version: '2.67.0' })
        )
        expect(JSON.stringify(events)).not.toContain('private response content')
        expect(JSON.stringify(events)).not.toContain('posthog/posthog')
    })

    it('does not create a server run for local execution', async () => {
        logic.actions.openLibrary('stable-key')
        logic.actions.selectProgram(program)
        logic.actions.setLibraryEnvironment('local')

        logic.actions.createRun()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockWizardRunsCreate).not.toHaveBeenCalled()
        expect(posthog.capture).not.toHaveBeenCalledWith('wizard run create requested', expect.anything())
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
        const createdRun = makeRun()
        mockWizardRunsCreate.mockResolvedValueOnce(createdRun)
        const detailsLogic = wizardRunDetailsLogic()
        detailsLogic.mount()
        logic.actions.openLibrary('stable-key')
        logic.actions.selectProgram(program)
        logic.actions.setRepository('posthog/posthog')

        logic.actions.createRun()
        await expectLogic(logic).toFinishAllListeners()

        expect(detailsLogic.values.selectedRunSummary?.id).toBe('run-new')
        expect(posthog.capture).toHaveBeenCalledWith('wizard run create succeeded', {
            event_source: 'wizard_ui',
            project_id: '1',
            environment: 'cloud',
            run_surface: 'cloud',
            wizard_run_id: 'run-new',
            task_run_id: 'run-new',
            program_id: program.id,
            wizard_version: '2.67.0',
            version: '2.67.0',
            command: 'default',
            workspace_type: 'git_repository',
            status: 'created',
        })
        expect(posthog.capture).not.toHaveBeenCalledWith('setup wizard finished', expect.anything())
        expect(JSON.stringify(jest.mocked(posthog.capture).mock.calls)).not.toContain('example/private-project')
        detailsLogic.unmount()
    })

    it('selects the retried program after the registry reloads', async () => {
        mockWizardRegistryList.mockResolvedValue({
            count: 2,
            next: null,
            previous: null,
            results: [program, localProgram],
        })
        const run = makeRun({ id: 'run-old' })

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
        const run = makeRun({ id: 'run-old' })

        logic.actions.runAgain(run as any)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.selectedProgram).toBeNull()
        expect(logic.values.programSelectionInvalidated).toBe(true)
    })
})
