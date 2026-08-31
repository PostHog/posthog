import { expectLogic } from 'kea-test-utils'

import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import { wizardRunsList } from './generated/api'
import type { WizardRunApi } from './generated/api.schemas'
import { wizardRunsLogic } from './wizardRunsLogic'

jest.mock('./generated/api', () => ({ wizardRunsList: jest.fn() }))

const mockWizardRunsList = wizardRunsList as jest.Mock

function makeRun(): WizardRunApi {
    return {
        id: 'run-1',
        team_id: 1,
        created_by_id: 1,
        environment: 'cloud',
        workspace: { type: 'git_repository', repository: 'posthog/posthog' },
        program: {
            id: 'posthog-integration',
            name: 'PostHog integration',
            description: 'Set up PostHog',
            wizard_version: '2.6.0',
            command: [],
            tags: [],
            required_programs: [],
            supported_environments: ['local', 'cloud'],
        },
        status: 'running',
        error_code: null,
        error_message: null,
        stage: 'executing_wizard',
        created_at: '2026-08-26T10:00:00Z',
        updated_at: '2026-08-26T10:01:00Z',
        started_at: '2026-08-26T10:00:30Z',
        finished_at: null,
        deadline_at: '2026-08-26T11:00:00Z',
    }
}

describe('wizardRunsLogic', () => {
    let logic: ReturnType<typeof wizardRunsLogic.build>

    beforeEach(async () => {
        initKeaTests()
        mockWizardRunsList.mockReset()
        mockWizardRunsList.mockResolvedValue({ count: 1, next: null, previous: null, results: [makeRun()] })
        await expectLogic(projectLogic).toMatchValues({ currentProjectId: expect.any(Number) })
        logic = wizardRunsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('keeps resolved rows visible during background polling', async () => {
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                runsInitialLoading: false,
                runs: [expect.objectContaining({ id: 'run-1' })],
            })

        mockWizardRunsList.mockReturnValue(new Promise(() => {}))
        logic.actions.loadRuns()

        await expectLogic(logic).toMatchValues({
            runsLoading: true,
            runsInitialLoading: false,
            runs: [expect.objectContaining({ id: 'run-1' })],
        })
    })

    it('searches runs by repository name', async () => {
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSearch('posthog/posthog')

        await expectLogic(logic).toMatchValues({
            filteredRuns: [expect.objectContaining({ id: 'run-1' })],
        })
    })

    it('distinguishes filtered results from an empty run history', async () => {
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSearch('missing program')

        await expectLogic(logic).toMatchValues({
            filteredRuns: [],
            hasRunFilters: true,
            runs: [expect.objectContaining({ id: 'run-1' })],
        })
    })
})
