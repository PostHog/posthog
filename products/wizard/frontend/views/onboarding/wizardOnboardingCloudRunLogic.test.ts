import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'
import { installMockEventSource } from 'lib/wizard-sync/eventSource.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { PreflightStatus } from '~/types'

import { wizardRegistryList, wizardRunsCreate } from '../../generated/api'
import type { WizardProgramApi, WizardRunApi } from '../../generated/api.schemas'
import { onboardingWizardRunLogic } from './onboardingWizardRunLogic'
import { wizardOnboardingCloudRunLogic } from './wizardOnboardingCloudRunLogic'

jest.mock('../../generated/api', () => ({
    wizardRegistryList: jest.fn(),
    wizardRunsCreate: jest.fn(),
    wizardRunsList: jest.fn().mockResolvedValue({ results: [], next: null }),
    wizardRunsTasksRetrieve: jest.fn().mockResolvedValue({ tasks: [] }),
    getWizardRunsStreamRetrieveUrl: () => '/stream',
}))
jest.mock('../../lib/wizardApi', () => ({
    loadWizardRunArtifacts: jest.fn().mockResolvedValue([]),
    loadWizardOnboardingStartTime: jest.fn().mockImplementation(async () => new Date().toISOString()),
}))

const props = { projectId: String(MOCK_DEFAULT_TEAM.id), userId: MOCK_DEFAULT_USER.id }
const program: WizardProgramApi = {
    id: 'posthog-integration',
    name: 'PostHog integration',
    description: 'Install PostHog',
    wizard_version: '2.67.0',
    command: [],
    tags: [],
    required_programs: [],
    supported_environments: ['cloud', 'local'],
}

describe('wizardOnboardingCloudRunLogic', () => {
    let logic: ReturnType<typeof wizardOnboardingCloudRunLogic.build>
    let restoreEventSource: () => void
    let run: WizardRunApi

    beforeEach(async () => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/': {
                    results: [
                        {
                            id: 1,
                            kind: 'github',
                            config: { account: { name: 'example', type: 'Organization' } },
                            created_at: '2026-01-01T00:00:00Z',
                        },
                    ],
                },
            },
        })
        initKeaTests()
        restoreEventSource = installMockEventSource()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WIZARD_ONBOARDING_CLOUD_RUNS_ENABLED]: true })
        preflightLogic.actions.loadPreflightSuccess({
            cloud: true,
            wizard_cloud_run_available: true,
        } as PreflightStatus)
        jest.mocked(wizardRegistryList).mockResolvedValue({ count: 1, results: [program] })
        run = {
            id: 'cloud-installation',
            team_id: MOCK_DEFAULT_TEAM.id,
            created_by_id: props.userId,
            created_by: null,
            program,
            environment: 'cloud',
            workspace: { type: 'git_repository', repository: 'example/sample-project' },
            status: 'created',
            stage: 'dispatching',
            created_at: new Date(Date.now() - 60_000).toISOString(),
            updated_at: null,
            started_at: null,
            finished_at: null,
            deadline_at: null,
            error_code: null,
            error_message: null,
        }
        jest.mocked(wizardRunsCreate).mockReset().mockResolvedValue(run)
        logic = wizardOnboardingCloudRunLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WIZARD_ONBOARDING_CLOUD_RUNS_ENABLED]: true })
        preflightLogic.actions.loadPreflightSuccess({
            cloud: true,
            wizard_cloud_run_available: true,
        } as PreflightStatus)
        expect(logic.values.githubIntegration?.id).toBe(1)
        expect(logic.values.cloudRunEnabled).toBe(true)
        logic.actions.setRepository('example/sample-project')
    })

    afterEach(() => {
        logic.unmount()
        restoreEventSource()
        localStorage.clear()
        jest.restoreAllMocks()
    })

    it('creates one run and immediately restores progress despite a browser clock ahead of the server', async () => {
        logic.actions.startCloudRun()
        logic.actions.startCloudRun()
        await expectLogic(logic).toFinishAllListeners()
        expect(wizardRunsCreate).toHaveBeenCalledTimes(1)
        expect(wizardRunsCreate).toHaveBeenCalledWith(props.projectId, {
            program_id: program.id,
            wizard_version: program.wizard_version,
            environment: 'cloud',
            workspace: { type: 'git_repository', repository: 'example/sample-project' },
            idempotency_key: expect.any(String),
        })
        expect(onboardingWizardRunLogic(props).values.run).toEqual(run)
        logic.actions.startCloudRun()
        expect(wizardRunsCreate).toHaveBeenCalledTimes(1)
        featureFlagLogic.actions.setFeatureFlags([], {})
        expect(onboardingWizardRunLogic(props).values.run).toEqual(run)
    })

    it('reuses the request key after failure and replaces it for a different repository', async () => {
        jest.mocked(wizardRunsCreate).mockRejectedValue(new Error('offline'))
        const key = logic.values.idempotencyKey
        logic.actions.startCloudRun()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.createError).toContain('try again')
        logic.actions.startCloudRun()
        await expectLogic(logic).toFinishAllListeners()
        expect(jest.mocked(wizardRunsCreate).mock.calls.map(([, body]) => body.idempotency_key)).toEqual([key, key])
        logic.actions.setRepository('example/another-project')
        expect(logic.values.idempotencyKey).not.toBe(key)
    })

    it.each(['flag', 'instance', 'repository', 'program'])(
        'does not start a run without the required %s',
        async (missing) => {
            if (missing === 'flag') {
                featureFlagLogic.actions.setFeatureFlags([], {})
            }
            if (missing === 'instance') {
                preflightLogic.actions.loadPreflightSuccess({
                    cloud: true,
                    wizard_cloud_run_available: false,
                } as PreflightStatus)
            }
            if (missing === 'repository') {
                logic.actions.setRepository('')
            }
            if (missing === 'program') {
                logic.actions.loadRegistrySuccess([{ ...program, supported_environments: ['local'] }])
            }
            logic.actions.startCloudRun()
            await expectLogic(logic).toFinishAllListeners()
            expect(wizardRunsCreate).not.toHaveBeenCalled()
        }
    )
})
