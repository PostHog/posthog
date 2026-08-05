import { waitFor } from '@testing-library/react'
/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SignalTeamConfig } from '../types'
import { signalTeamConfigLogic } from './signalTeamConfigLogic'

describe('signalTeamConfigLogic', () => {
    let logic: ReturnType<typeof signalTeamConfigLogic.build>
    let lastPostBody: Partial<SignalTeamConfig> | null

    const mountWith = async (baseBranches: Record<string, string>): Promise<void> => {
        let serverConfig: SignalTeamConfig = {
            id: 'cfg-1',
            autostart_enabled: true,
            default_autostart_priority: 'P4',
            autostart_base_branches: baseBranches,
        }
        lastPostBody = null
        useMocks({
            get: { '/api/projects/:team_id/signals/config/': () => [200, serverConfig] },
            post: {
                '/api/projects/:team_id/signals/config/': async ({ request }) => {
                    lastPostBody = (await request.json()) as Partial<SignalTeamConfig>
                    serverConfig = { ...serverConfig, ...lastPostBody }
                    return [200, serverConfig]
                },
            },
        })
        initKeaTests()
        logic = signalTeamConfigLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    afterEach(() => logic?.unmount())

    it('adds an override without clobbering existing repos, and clears the draft', async () => {
        await mountWith({ 'acme/web': 'staging' })
        logic.actions.setDraftBaseBranchRepo('Acme/API')
        logic.actions.setDraftBaseBranchBranch('  develop  ')
        logic.actions.addBaseBranchOverride()
        await expectLogic(logic).toFinishAllListeners()

        expect(lastPostBody?.autostart_base_branches).toEqual({ 'acme/web': 'staging', 'acme/api': 'develop' })
        expect(logic.values.draftBaseBranchRepo).toBe('')
        expect(logic.values.draftBaseBranchBranch).toBe('')
        expect(logic.values.baseBranchOverrides).toEqual([
            { repo: 'acme/api', branch: 'develop' },
            { repo: 'acme/web', branch: 'staging' },
        ])
    })

    it('keeps the draft available when adding an override fails', async () => {
        const serverConfig: SignalTeamConfig = {
            id: 'cfg-1',
            autostart_enabled: true,
            default_autostart_priority: 'P4',
            autostart_base_branches: {},
        }
        useMocks({
            get: { '/api/projects/:team_id/signals/config/': () => [200, serverConfig] },
            post: { '/api/projects/:team_id/signals/config/': () => [500, { detail: 'Failed to save' }] },
        })
        initKeaTests()
        logic = signalTeamConfigLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setDraftBaseBranchRepo('acme/api')
        logic.actions.setDraftBaseBranchBranch('develop')
        logic.actions.addBaseBranchOverride()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.draftBaseBranchRepo).toBe('acme/api')
        expect(logic.values.draftBaseBranchBranch).toBe('develop')
        expect(logic.values.teamConfigUpdating).toBe(false)
        expect(logic.values.baseBranchOverrides).toEqual([])
    })

    it.each([
        ['repo without a slash', 'acmeweb', 'develop'],
        ['repo with an empty half', 'acme/', 'develop'],
        ['blank branch', 'acme/api', '   '],
    ])('does not persist an incomplete draft (%s)', async (_label, repo, branch) => {
        await mountWith({ 'acme/web': 'staging' })
        logic.actions.setDraftBaseBranchRepo(repo)
        logic.actions.setDraftBaseBranchBranch(branch)
        logic.actions.addBaseBranchOverride()
        await expectLogic(logic).toFinishAllListeners()

        expect(lastPostBody).toBeNull()
        expect(logic.values.baseBranchOverrides).toEqual([{ repo: 'acme/web', branch: 'staging' }])
    })

    it('drops the drafted branch when the repository changes', async () => {
        await mountWith({})
        logic.actions.setDraftBaseBranchRepo('acme/web')
        logic.actions.setDraftBaseBranchBranch('release/web')
        logic.actions.setDraftBaseBranchRepo('acme/api')

        expect(logic.values.draftBaseBranchBranch).toBe('')
        expect(logic.values.addBaseBranchOverrideDisabledReason).toBe('Choose a branch first')
    })

    it('updates an existing override branch without touching others', async () => {
        await mountWith({ 'acme/web': 'staging', 'acme/api': 'develop' })
        logic.actions.updateBaseBranchOverride('acme/web', 'release')
        await expectLogic(logic).toFinishAllListeners()

        expect(lastPostBody?.autostart_base_branches).toEqual({ 'acme/web': 'release', 'acme/api': 'develop' })
    })

    it('serializes rapid override updates so the latest map is persisted last', async () => {
        const initialConfig: SignalTeamConfig = {
            id: 'cfg-1',
            autostart_enabled: true,
            default_autostart_priority: 'P4',
            autostart_base_branches: { 'acme/web': 'staging' },
        }
        const postBodies: Partial<SignalTeamConfig>[] = []
        let resolveFirstUpdate: (() => void) | undefined
        const firstUpdatePending = new Promise<void>((resolve) => {
            resolveFirstUpdate = resolve
        })

        useMocks({
            get: { '/api/projects/:team_id/signals/config/': () => [200, initialConfig] },
            post: {
                '/api/projects/:team_id/signals/config/': async ({ request }) => {
                    const body = (await request.json()) as Partial<SignalTeamConfig>
                    postBodies.push(body)
                    if (postBodies.length === 1) {
                        await firstUpdatePending
                    }
                    return [200, { ...initialConfig, ...body }]
                },
            },
        })
        initKeaTests()
        logic = signalTeamConfigLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.updateBaseBranchOverride('acme/web', 'release-one')
        logic.actions.updateBaseBranchOverride('acme/web', 'release-two')

        await waitFor(() => expect(postBodies).toHaveLength(1))
        expect(logic.values.teamConfigUpdating).toBe(true)
        resolveFirstUpdate?.()
        await expectLogic(logic).toFinishAllListeners()

        expect(postBodies).toEqual([
            { autostart_base_branches: { 'acme/web': 'release-one' } },
            { autostart_base_branches: { 'acme/web': 'release-two' } },
        ])
        expect(logic.values.teamConfigUpdating).toBe(false)
    })

    it('does not persist an update to the branch already stored', async () => {
        await mountWith({ 'acme/web': 'staging' })
        logic.actions.updateBaseBranchOverride('acme/web', 'staging')
        await expectLogic(logic).toFinishAllListeners()

        expect(lastPostBody).toBeNull()
    })

    it('removes only the targeted override', async () => {
        await mountWith({ 'acme/web': 'staging', 'acme/api': 'develop' })
        logic.actions.removeBaseBranchOverride('acme/web')
        await expectLogic(logic).toFinishAllListeners()

        expect(lastPostBody?.autostart_base_branches).toEqual({ 'acme/api': 'develop' })
        expect(logic.values.baseBranchOverrides).toEqual([{ repo: 'acme/api', branch: 'develop' }])
    })
})
