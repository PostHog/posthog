import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api'
import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import { wizardRunsPartialUpdate, wizardRunsRetrieve } from './generated/api'
import type { WizardRunApi, WizardRunGitDiffArtifactApi } from './generated/api.schemas'
import { loadWizardRunArtifactContent, loadWizardRunArtifacts } from './wizardApi'
import { wizardRunDetailsLogic } from './wizardRunDetailsLogic'

jest.mock('./generated/api', () => ({
    wizardRunsList: jest.fn().mockResolvedValue({ count: 0, next: null, previous: null, results: [] }),
    wizardRunsPartialUpdate: jest.fn(),
    wizardRunsRetrieve: jest.fn(),
}))

jest.mock('./wizardApi', () => ({
    loadWizardRunArtifactContent: jest.fn(),
    loadWizardRunArtifacts: jest.fn(),
}))

const mockLoadWizardRunArtifactContent = loadWizardRunArtifactContent as jest.Mock
const mockLoadWizardRunArtifacts = loadWizardRunArtifacts as jest.Mock
const mockWizardRunsRetrieve = wizardRunsRetrieve as jest.Mock

const gitDiffArtifact: WizardRunGitDiffArtifactApi = {
    id: 'artifact-1',
    team_id: 1,
    run_id: 'run-1',
    artifact_type: 'git_diff',
    size_bytes: 512,
    content_hash: 'diff-hash',
    additions: 2,
    removals: 1,
    created_at: '2026-08-26T10:02:00Z',
}

function makeRun(): WizardRunApi {
    return {
        id: 'run-1',
        team_id: 1,
        created_by_id: 1,
        created_by: { id: 1, first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.com' },
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

describe('wizardRunDetailsLogic', () => {
    let logic: ReturnType<typeof wizardRunDetailsLogic.build>

    beforeEach(async () => {
        initKeaTests()
        jest.spyOn(posthog, 'capture').mockClear()
        mockWizardRunsRetrieve.mockReset()
        mockLoadWizardRunArtifactContent.mockReset()
        mockLoadWizardRunArtifacts.mockReset()
        mockWizardRunsRetrieve.mockResolvedValue(makeRun())
        mockLoadWizardRunArtifactContent.mockResolvedValue('diff content')
        mockLoadWizardRunArtifacts.mockResolvedValue([])
        await expectLogic(projectLogic).toMatchValues({ currentProjectId: expect.any(Number) })
        logic = wizardRunDetailsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('loads run details and artifacts through separate endpoints', async () => {
        logic.actions.selectRun(makeRun())

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                selectedRun: expect.objectContaining({ id: 'run-1' }),
                selectedRunArtifacts: [],
                selectedRunArtifactsInitialLoading: false,
            })

        expect(mockWizardRunsRetrieve).toHaveBeenCalledWith(expect.any(String), 'run-1')
        expect(mockLoadWizardRunArtifacts).toHaveBeenCalledWith(expect.any(String), 'run-1')
        expect(mockLoadWizardRunArtifactContent).not.toHaveBeenCalled()
        expect(posthog.capture).toHaveBeenCalledWith(
            'wizard run viewed',
            expect.objectContaining({
                wizard_run_id: 'run-1',
                task_run_id: 'run-1',
                run_surface: 'cloud',
                version: '2.6.0',
            })
        )
    })

    it('loads git diff content only after the artifact is opened', async () => {
        mockLoadWizardRunArtifacts.mockResolvedValue([gitDiffArtifact])
        logic.actions.selectRun(makeRun())
        await expectLogic(logic).toFinishAllListeners()

        expect(mockLoadWizardRunArtifactContent).not.toHaveBeenCalled()

        logic.actions.openRunDiff(gitDiffArtifact)

        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            selectedRunDiffArtifactId: 'artifact-1',
            selectedRunDiffContent: 'diff content',
            runDiffLoading: false,
        })
        expect(mockLoadWizardRunArtifactContent).toHaveBeenCalledWith(expect.any(String), 'run-1', 'artifact-1')
        expect(posthog.capture).toHaveBeenCalledWith(
            'wizard run diff opened',
            expect.objectContaining({
                wizard_run_id: 'run-1',
                artifact_type: 'git_diff',
            })
        )
        expect(JSON.stringify(jest.mocked(posthog.capture).mock.calls)).not.toContain('diff content')
    })

    it('reuses downloaded diff content when the same artifact is reopened', async () => {
        mockLoadWizardRunArtifacts.mockResolvedValue([gitDiffArtifact])
        logic.actions.selectRun(makeRun())
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openRunDiff(gitDiffArtifact)
        await expectLogic(logic).toFinishAllListeners()
        expect(mockLoadWizardRunArtifactContent).toHaveBeenCalledTimes(1)

        logic.actions.closeRunDiff()
        logic.actions.openRunDiff(gitDiffArtifact)

        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            selectedRunDiffContent: 'diff content',
        })
        expect(mockLoadWizardRunArtifactContent).toHaveBeenCalledTimes(1)
    })

    it('fetches artifacts once more when a poll reveals the run finished', async () => {
        logic.actions.selectRun(makeRun())
        await expectLogic(logic).toFinishAllListeners()

        mockWizardRunsRetrieve.mockResolvedValue({ ...makeRun(), status: 'completed', stage: null })

        logic.actions.loadRunDetails({ runId: 'run-1' })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockLoadWizardRunArtifacts).toHaveBeenCalledTimes(2)

        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadRunDetails({ runId: 'run-1' })
        await expectLogic(logic).toFinishAllListeners()
        expect(mockLoadWizardRunArtifacts).toHaveBeenCalledTimes(2)
        expect(jest.mocked(posthog.capture).mock.calls.filter(([event]) => event === 'wizard run viewed')).toHaveLength(
            1
        )
    })

    it('does not download a diff that is too large to render', async () => {
        const largeArtifact = { ...gitDiffArtifact, size_bytes: 2 * 1024 * 1024 + 1 }

        logic.actions.openRunDiff(largeArtifact)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockLoadWizardRunArtifactContent).not.toHaveBeenCalled()
    })

    it('asks for confirmation before canceling a run', async () => {
        const openDialog = jest.spyOn(LemonDialog, 'open').mockReturnValue(undefined)

        logic.actions.cancelRun(makeRun())
        await expectLogic(logic).toFinishAllListeners()

        expect(openDialog).toHaveBeenCalledWith(
            expect.objectContaining({
                title: 'Cancel Wizard run?',
                primaryButton: expect.objectContaining({ children: 'Cancel run', status: 'danger' }),
            })
        )
        expect(posthog.capture).not.toHaveBeenCalledWith('wizard run cancel requested', expect.anything())
    })

    it.each([true, false])('tracks the confirmed cancellation outcome: %s', async (succeeded) => {
        jest.spyOn(console, 'error').mockImplementation()
        if (succeeded) {
            jest.mocked(wizardRunsPartialUpdate).mockResolvedValue({ ...makeRun(), status: 'cancelled' })
        } else {
            jest.mocked(wizardRunsPartialUpdate).mockRejectedValue(new ApiError('private response content', 503))
        }

        logic.actions.cancelRunRequest({ runId: 'run-1' })
        await expectLogic(logic).toFinishAllListeners()

        const events = jest
            .mocked(posthog.capture)
            .mock.calls.filter(([event]) => event.startsWith('wizard run cancel'))
        expect(events.map(([event]) => event)).toEqual([
            'wizard run cancel requested',
            succeeded ? 'wizard run cancel succeeded' : 'wizard run cancel failed',
        ])
        expect(events[1][1]).toEqual(expect.objectContaining({ wizard_run_id: 'run-1' }))
        if (!succeeded) {
            expect(events[1][1]).toEqual(expect.objectContaining({ http_status: 503 }))
        }
        expect(JSON.stringify(events)).not.toContain('private response content')
        expect(posthog.capture).not.toHaveBeenCalledWith('setup wizard finished', expect.anything())
    })

    it('prefers a newer run summary over stale cached details', async () => {
        logic.actions.selectRun(makeRun())
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ selectedRun: expect.objectContaining({ status: 'running' }) })

        // Reopen after the run finished while the drawer was closed: the table summary is newer
        // than the details still cached from the previous session, and the refresh has not landed.
        mockWizardRunsRetrieve.mockReturnValue(new Promise(() => {}))
        logic.actions.selectRun({
            ...makeRun(),
            status: 'completed',
            updated_at: '2026-08-26T10:05:00Z',
            finished_at: '2026-08-26T10:05:00Z',
        })

        await expectLogic(logic).toMatchValues({
            selectedRun: expect.objectContaining({ status: 'completed' }),
        })
    })

    it('records an artifact load failure and clears it on a successful retry', async () => {
        mockLoadWizardRunArtifacts.mockRejectedValueOnce(new Error('network down'))
        logic.actions.selectRun(makeRun())
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ runArtifactsError: expect.any(String) })

        mockLoadWizardRunArtifacts.mockResolvedValue([])
        logic.actions.refreshSelectedRun()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ runArtifactsError: null })
    })

    it('keeps resolved artifact state visible during a refresh', async () => {
        logic.actions.selectRun(makeRun())
        await expectLogic(logic).toFinishAllListeners()

        mockLoadWizardRunArtifacts.mockReturnValue(new Promise(() => {}))
        logic.actions.refreshSelectedRun()

        await expectLogic(logic).toMatchValues({
            runArtifactsLoading: true,
            selectedRunArtifactsInitialLoading: false,
        })
    })
})
