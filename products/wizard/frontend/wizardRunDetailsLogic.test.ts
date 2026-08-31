import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from '@posthog/lemon-ui'

import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import { wizardRunsRetrieve } from './generated/api'
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
