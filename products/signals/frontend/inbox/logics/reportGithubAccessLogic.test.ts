import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeReport } from '../__mocks__/inboxMocks'
import { reportGithubAccessLogic } from './reportGithubAccessLogic'

describe('reportGithubAccessLogic', () => {
    let logic: ReturnType<typeof reportGithubAccessLogic.build>
    let integrationStatus: number
    let repositoryStatus: number
    let repositories: string[]
    let githubOptional: boolean
    let setupStatus: number

    beforeEach(() => {
        localStorage.clear()
        integrationStatus = 200
        repositoryStatus = 200
        repositories = ['example/app']
        githubOptional = true
        setupStatus = 200
        useMocks({
            get: {
                '/api/projects/:project/signals/scout/configs/': [],
                '/api/projects/:project/signals/onboarding/': () => [
                    setupStatus,
                    {
                        draft: null,
                        completed_at: null,
                        github_optional_available: githubOptional,
                    },
                ],
                '/api/projects/:project/integrations/': () => [
                    integrationStatus,
                    { results: [{ id: 1, kind: 'github', installation_status: 'connected' }], next: null },
                ],
                '/api/projects/:project/integrations/1/github_repository_access/': () => [
                    repositoryStatus,
                    { available: repositories.includes('example/app') },
                ],
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {})
    })

    afterEach(() => logic?.unmount())

    it.each([
        ['accessible', ['example/app'], 200, 200, null, true, 200],
        ['empty installation', [], 200, 200, 'repair', true, 200],
        ['different repository', ['example/other'], 200, 200, 'repair', true, 200],
        ['repository request failed', [], 200, 503, 'retry', true, 200],
        ['integration request failed', [], 503, 200, 'retry', true, 200],
        ['pilot eligibility request failed', [], 200, 200, null, true, 503],
        ['non-pilot eligibility request failed', [], 200, 200, null, false, 503],
        ['pilot disabled', [], 200, 200, null, false, 200],
    ] as const)(
        'handles %s without confusing failed checks with missing access',
        async (_, repos, integrationCode, repositoryCode, expected, pilot, setupCode) => {
            const capture = jest.spyOn(posthog, 'capture')
            repositories = [...repos]
            integrationStatus = integrationCode
            repositoryStatus = repositoryCode
            githubOptional = pilot
            setupStatus = setupCode
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SELF_DRIVING_GITHUB_OPTIONAL], {
                [FEATURE_FLAGS.SELF_DRIVING_GITHUB_OPTIONAL]: !pilot,
            })
            logic = reportGithubAccessLogic({ report: makeReport({ id: 'github-access', repo_slug: 'example/app' }) })
            logic.mount()
            await waitFor(() => expect(logic.values.loading).toBe(false))
            expect(logic.values.repairNeeded).toBe(expected === 'repair')
            expect(logic.values.failed).toBe(expected === 'retry')
            if (expected === null) {
                expect(logic.values.disabledReason).toBeNull()
            }
            if (expected === 'retry') {
                integrationStatus = 200
                repositoryStatus = 200
                repositories = ['example/app']
                setupStatus = 200
                logic.actions.retryAccess()
                await waitFor(() => expect(logic.values.disabledReason).toBeNull())
                expect(capture).toHaveBeenCalledWith(
                    'Inbox report action',
                    expect.objectContaining({ report_id: 'github-access', surface: 'detail_pane', stage: 'retry' }),
                    undefined
                )
                expect(capture).toHaveBeenCalledWith(
                    'Inbox report action',
                    expect.objectContaining({ outcome: 'available' }),
                    undefined
                )
            }
        }
    )

    it.each([true, false])(
        'does not gate implementation before eligibility is known (team loaded: %s)',
        async (teamLoaded) => {
            let finish!: () => void
            const pending = new Promise<void>((resolve) => (finish = resolve))
            useMocks({
                get: {
                    '/api/projects/:project/signals/onboarding/': async () => {
                        await pending
                        return { draft: null, completed_at: null, github_optional_available: false }
                    },
                },
            })
            if (!teamLoaded) {
                teamLogic.actions.loadCurrentTeamSuccess(null)
            }
            logic = reportGithubAccessLogic({ report: makeReport() })
            logic.mount()
            try {
                await waitFor(() => expect(logic.values.integrationsLoading).toBe(false))
                expect(logic.values.savedStateLoading).toBe(teamLoaded)
                expect(logic.values.failed).toBe(false)
                expect(logic.values.repairNeeded).toBe(false)
                expect(logic.values.disabledReason).toBeNull()
            } finally {
                finish()
                await expectLogic(logic).toFinishAllListeners()
            }
        }
    )

    it('enables implementation before an unrelated installation finishes checking', async () => {
        let finishSlowCheck!: () => void
        const slowCheck = new Promise<void>((resolve) => (finishSlowCheck = resolve))
        useMocks({
            get: {
                '/api/projects/:project/integrations/': {
                    results: [1, 2].map((id) => ({ id, kind: 'github', installation_status: 'connected' })),
                    next: null,
                },
                '/api/projects/:project/integrations/1/github_repository_access/': async () => {
                    await slowCheck
                    return [503, {}]
                },
                '/api/projects/:project/integrations/2/github_repository_access/': { available: true },
            },
        })
        logic = reportGithubAccessLogic({ report: makeReport({ id: 'github-access', repo_slug: 'example/app' }) })
        logic.mount()
        try {
            await waitFor(() => expect(logic.values.access).toBe('available'))
            expect(logic.values.disabledReason).toBeNull()
            expect(logic.values.loading).toBe(false)
        } finally {
            finishSlowCheck()
        }
    })

    it.each([200, 503])('ignores a superseded probe result (status %i)', async (status) => {
        let finish!: () => void
        let started!: () => void
        const pending = new Promise<void>((resolve) => (finish = resolve))
        const requested = new Promise<void>((resolve) => (started = resolve))
        useMocks({
            get: {
                '/api/projects/:project/integrations/1/github_repository_access/': async () => {
                    started()
                    await pending
                    return [status, { available: true }]
                },
            },
        })
        logic = reportGithubAccessLogic({ report: makeReport({ id: 'changing-access', repo_slug: 'example/app' }) })
        logic.mount()
        await requested
        integrationsLogic.actions.loadIntegrationsSuccess([])
        await waitFor(() => expect(logic.values.access).toBe('unavailable'))
        finish()
        await expectLogic(logic).toFinishListeners()
        await waitFor(() => expect(logic.values.accessLoading).toBe(false))
        expect(logic.values.access).toBe('unavailable')
        expect(logic.values.failed).toBe(false)
    })
})
