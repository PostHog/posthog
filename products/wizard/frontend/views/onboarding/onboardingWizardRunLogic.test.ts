import { MOCK_DEFAULT_USER } from 'lib/api.mock'
import { installMockEventSource } from 'lib/wizard-sync/eventSource.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { wizardRunsList, wizardRunsTasksRetrieve } from '../../generated/api'
import type { WizardRunApi } from '../../generated/api.schemas'
import { loadWizardRunArtifacts } from '../../lib/wizardApi'
import { wizardRunSyncLogic } from '../../logics/wizardRunSyncLogic'
import { onboardingWizardRunLogic } from './onboardingWizardRunLogic'

jest.mock('../../generated/api', () => ({
    wizardRunsList: jest.fn().mockResolvedValue({ results: [], next: null }),
    wizardRunsTasksRetrieve: jest.fn().mockResolvedValue({ tasks: [] }),
    getWizardRunsStreamRetrieveUrl: () => '/stream',
}))
jest.mock('../../lib/wizardApi', () => ({
    loadWizardRunArtifacts: jest.fn().mockResolvedValue([]),
    loadWizardOnboardingStartTime: jest.fn().mockImplementation(async () => new Date().toISOString()),
}))

const props = { projectId: '1', userId: MOCK_DEFAULT_USER.id }
const startedAt = '2026-09-23T10:00:00Z'
const run: WizardRunApi = {
    id: 'installation',
    team_id: 1,
    created_by_id: props.userId,
    program: {
        id: 'posthog-integration',
        name: 'PostHog integration',
        description: '',
        command: [],
        wizard_version: '1.0.0',
        tags: [],
        required_programs: [],
        supported_environments: ['local', 'cloud'],
    },
    environment: 'local',
    workspace: { type: 'local_folder', project_name: 'example-project' },
    status: 'running',
    created_at: '2026-09-23T10:01:00Z',
    updated_at: '2026-09-23T10:01:00Z',
    created_by: null,
    stage: 'executing_wizard',
    error_code: null,
    error_message: null,
    started_at: null,
    finished_at: null,
    deadline_at: null,
}

describe('onboardingWizardRunLogic', () => {
    let logic: ReturnType<typeof onboardingWizardRunLogic.build>
    let restoreEventSource: () => void

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        restoreEventSource = installMockEventSource()
        jest.mocked(wizardRunsList).mockResolvedValue({ count: 0, results: [], next: null })
        localStorage.setItem(`1.${props.userId}.onboarding_wizard_started_at`, JSON.stringify(startedAt))
        logic = onboardingWizardRunLogic(props)
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        restoreEventSource()
        jest.restoreAllMocks()
        localStorage.clear()
    })

    it('ignores history, audits, and other users, then saves the installation and supersedes it with a newer one', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const sync = wizardRunSyncLogic({ projectId: '1' })
        const history = { ...run, id: 'history', created_at: '2026-09-23T09:00:00Z' }
        const audit = { ...run, id: 'audit', program: { ...run.program, id: 'analytics-audit' } }
        const otherUser = { ...run, id: 'other-user', created_by_id: props.userId + 1 }
        sync.actions.runsLoaded([history, audit, otherUser])
        expect(logic.values.run).toBeNull()

        sync.actions.runsLoaded([run, audit, history])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.savedRun).toEqual({ id: run.id, created_at: run.created_at })
        expect(JSON.parse(localStorage.getItem(`1.${props.userId}.onboarding_wizard_run_id`)!)).toEqual(
            logic.values.savedRun
        )
        const taskReads = jest.mocked(wizardRunsTasksRetrieve).mock.calls.length
        const artifactReads = jest.mocked(loadWizardRunArtifacts).mock.calls.length
        for (const updatedAt of ['2026-09-23T10:02:00Z', '2026-09-23T10:03:00Z']) {
            sync.actions.runUpdated(run.id, {
                status: 'running',
                stage: 'executing_wizard',
                error_code: null,
                error_message: null,
                updated_at: updatedAt,
                started_at: null,
                finished_at: null,
                tasks: [],
            })
        }
        await expectLogic(logic).toFinishAllListeners()
        expect(wizardRunsTasksRetrieve).toHaveBeenCalledTimes(taskReads)
        expect(loadWizardRunArtifacts).toHaveBeenCalledTimes(artifactReads)

        const newer = { ...run, id: 'replacement', environment: 'cloud' as const, created_at: '2026-09-23T10:02:00Z' }
        sync.actions.runsLoaded([run, newer, audit])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.run?.id).toBe(newer.id)
        expect(logic.values.savedRun?.id).toBe(newer.id)
    })

    it.each(['completed', 'failed', 'cancelled'] as const)(
        'restores the saved %s installation after a fresh app mount',
        async (status) => {
            await expectLogic(logic).toFinishAllListeners()
            const terminal = { ...run, status }
            wizardRunSyncLogic({ projectId: '1' }).actions.runsLoaded([terminal])
            await expectLogic(logic).toFinishAllListeners()
            logic.unmount()

            initKeaTests()
            jest.mocked(wizardRunsList).mockResolvedValue({ count: 1, results: [terminal], next: null })
            logic = onboardingWizardRunLogic(props)
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.onboardingStartedAt).toBe(startedAt)
            expect(logic.values.run).toEqual(terminal)
            expect(wizardRunsTasksRetrieve).toHaveBeenCalledWith('1', run.id)
        }
    )

    it('does not restore another project or account selection', async () => {
        await expectLogic(logic).toFinishAllListeners()
        wizardRunSyncLogic({ projectId: '1' }).actions.runsLoaded([run])
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()
        logic = onboardingWizardRunLogic({ projectId: '2', userId: props.userId + 1 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.savedRun).toBeNull()
        expect(logic.values.run).toBeNull()
    })

    it('persists the initial onboarding start before any run exists', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()
        localStorage.clear()
        initKeaTests()
        logic = onboardingWizardRunLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const initialStart = logic.values.onboardingStartedAt
        expect(Number.isFinite(Date.parse(initialStart!))).toBe(true)
        expect(JSON.parse(localStorage.getItem(`1.${props.userId}.onboarding_wizard_started_at`)!)).toBe(initialStart)
        logic.unmount()
        initKeaTests()
        logic = onboardingWizardRunLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.onboardingStartedAt).toBe(initialStart)
        expect(logic.values.savedRun).toBeNull()
    })
})
