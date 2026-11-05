import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'
import { installMockEventSource } from 'lib/wizard-sync/eventSource.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { PreflightStatus } from '~/types'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

import { wizardRegistryList, wizardRunsCreate, wizardRunsList, wizardRunsTasksRetrieve } from '../../generated/api'
import type { WizardProgramApi, WizardRunApi } from '../../generated/api.schemas'
import { wizardRunSyncLogic } from '../../logics/wizardRunSyncLogic'
import {
    WIZARD_SPEND_AUDIT_PROGRAM_ID,
    WIZARD_SPEND_AUDIT_URL_PARAM,
    wizardSpendAuditLogic,
} from './wizardSpendAuditLogic'

jest.mock('../../generated/api', () => ({
    wizardRegistryList: jest.fn(),
    wizardRunsCreate: jest.fn(),
    wizardRunsList: jest.fn(),
    wizardRunsTasksRetrieve: jest.fn().mockResolvedValue({ tasks: [] }),
    getWizardRunsStreamRetrieveUrl: () => '/stream',
}))
jest.mock('../../lib/wizardApi', () => ({
    loadWizardRunArtifacts: jest.fn().mockResolvedValue([]),
}))

const props = { projectId: String(MOCK_DEFAULT_TEAM.id), userId: MOCK_DEFAULT_USER.id }
const auditProgram: WizardProgramApi = {
    id: WIZARD_SPEND_AUDIT_PROGRAM_ID,
    name: 'Spend audit',
    description: 'Find ways to lower your bill',
    wizard_version: '2.67.0',
    command: [],
    tags: [],
    required_programs: [],
    supported_environments: ['cloud'],
}
const pageMeta = { next: null, previous: null, next_offset: null, total: 1 }
const repo = (fullName: string): GitHubRepoApi => ({ id: fullName.length, name: fullName, full_name: fullName })
const run: WizardRunApi = {
    id: 'spend-audit-run',
    team_id: MOCK_DEFAULT_TEAM.id,
    created_by_id: props.userId,
    created_by: null,
    program: auditProgram,
    environment: 'cloud',
    workspace: { type: 'git_repository', repository: 'example/web-app' },
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

describe('wizardSpendAuditLogic', () => {
    let logic: ReturnType<typeof wizardSpendAuditLogic.build>
    let restoreEventSource: () => void

    beforeEach(() => {
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
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.BILLING_OPTIMIZE_SPEND]: true })
        preflightLogic.actions.loadPreflightSuccess({
            cloud: true,
            wizard_cloud_run_available: true,
        } as PreflightStatus)
        jest.mocked(wizardRegistryList).mockResolvedValue({ count: 1, results: [auditProgram] })
        jest.mocked(wizardRunsList).mockResolvedValue({ count: 0, results: [], next: null, previous: null })
        jest.mocked(wizardRunsCreate).mockReset().mockResolvedValue(run)
        jest.spyOn(api.integrations, 'githubRepositories').mockResolvedValue({
            repositories: [repo('example/web-app')],
            has_more: false,
            ...pageMeta,
        })
    })

    // Mounting reloads preflight and flags from the API mocks, so the gates are set again afterwards.
    const mountLogic = async (): Promise<void> => {
        logic = wizardSpendAuditLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.BILLING_OPTIMIZE_SPEND]: true })
        preflightLogic.actions.loadPreflightSuccess({
            cloud: true,
            wizard_cloud_run_available: true,
        } as PreflightStatus)
    }

    afterEach(() => {
        logic.unmount()
        restoreEventSource()
        jest.restoreAllMocks()
    })

    it('starts the audit on the only repository without another click', async () => {
        await mountLogic()
        logic.actions.openModal('github_return')
        await expectLogic(logic).toFinishAllListeners()

        expect(wizardRunsCreate).toHaveBeenCalledTimes(1)
        expect(wizardRunsCreate).toHaveBeenCalledWith(props.projectId, {
            program_id: auditProgram.id,
            wizard_version: auditProgram.wizard_version,
            environment: 'cloud',
            workspace: { type: 'git_repository', repository: 'example/web-app' },
            idempotency_key: expect.any(String),
        })
        expect(logic.values.view).toBe('run')
        expect(logic.values.run?.id).toBe(run.id)
    })

    it.each([
        ['several repositories', { repositories: [repo('example/web-app'), repo('example/api')], has_more: false }],
        ['more repositories than one page', { repositories: [repo('example/web-app')], has_more: true }],
    ])('waits for a choice when the integration has %s', async (_, page) => {
        jest.mocked(api.integrations.githubRepositories).mockResolvedValue({ ...page, ...pageMeta })

        await mountLogic()
        logic.actions.openModal('billing_button')
        await expectLogic(logic).toFinishAllListeners()

        expect(wizardRunsCreate).not.toHaveBeenCalled()
        expect(logic.values.view).toBe('pick_repository')
        expect(logic.values.autoStartPending).toBe(false)

        logic.actions.setRepository('example/api')
        logic.actions.startAudit()
        await expectLogic(logic).toFinishAllListeners()
        expect(wizardRunsCreate).toHaveBeenCalledTimes(1)
    })

    it('follows an audit already in flight through to its result instead of starting another', async () => {
        jest.mocked(wizardRunsList).mockResolvedValue({
            count: 1,
            results: [{ ...run, status: 'running' }],
            next: null,
            previous: null,
        })

        await mountLogic()
        logic.actions.openModal('billing_button')
        await expectLogic(logic).toFinishAllListeners()

        expect(wizardRunsCreate).not.toHaveBeenCalled()
        expect(logic.values.view).toBe('run')
        expect(logic.values.run?.id).toBe(run.id)
        expect(wizardRunsTasksRetrieve).toHaveBeenCalledWith(props.projectId, run.id)

        const tasksCalls = jest.mocked(wizardRunsTasksRetrieve).mock.calls.length
        wizardRunSyncLogic({ projectId: props.projectId }).actions.runsLoaded([{ ...run, status: 'completed' }], true)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.view).toBe('run')
        expect(logic.values.run?.status).toBe('completed')
        expect(jest.mocked(wizardRunsTasksRetrieve).mock.calls.length).toBeGreaterThan(tasksCalls)
    })

    it('shows the latest finished audit after a reload, until the user starts another', async () => {
        const older = { ...run, id: 'older-audit', status: 'failed' as const, created_at: '2026-01-01T00:00:00Z' }
        jest.mocked(wizardRunsList).mockResolvedValue({
            count: 2,
            results: [older, { ...run, status: 'completed' }],
            next: null,
            previous: null,
        })

        await mountLogic()
        logic.actions.openModal('billing_button')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.view).toBe('run')
        expect(logic.values.run?.id).toBe(run.id)
        expect(wizardRunsCreate).not.toHaveBeenCalled()

        logic.actions.runAgain()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.run).toBeNull()
        expect(logic.values.view).toBe('pick_repository')
        expect(logic.values.autoStartPending).toBe(false)
        expect(wizardRunsCreate).not.toHaveBeenCalled()
    })

    it('reopens the modal when GitHub sends the user back', async () => {
        await mountLogic()
        const next = new URL(logic.values.connectGitHubUrl, 'http://localhost').searchParams.get('next')
        expect(next).toContain(`${WIZARD_SPEND_AUDIT_URL_PARAM}=start`)

        router.actions.push(next as string)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isModalOpen).toBe(true)
        expect(router.values.location.pathname).toBe('/organization/billing/overview')
        expect(router.values.searchParams[WIZARD_SPEND_AUDIT_URL_PARAM]).toBeUndefined()
    })

    it('does not offer the audit when the registry has no cloud program for it', async () => {
        jest.mocked(wizardRegistryList).mockResolvedValue({
            count: 1,
            results: [{ ...auditProgram, id: 'posthog-integration' }],
        })

        await mountLogic()
        logic.actions.openModal('billing_button')
        await expectLogic(logic).toFinishAllListeners()

        expect(wizardRunsCreate).not.toHaveBeenCalled()
        expect(logic.values.view).toBe('unavailable')
    })
})
