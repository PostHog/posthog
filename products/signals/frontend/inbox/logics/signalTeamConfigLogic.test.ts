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

    it('saves and clears the daily report limit through the draft', async () => {
        await mountWith({})
        logic.actions.setDraftMaxReportsPerDay(5)
        expect(logic.values.saveMaxReportsPerDayDisabledReason).toBeNull()
        logic.actions.saveDraftMaxReportsPerDay()
        await expectLogic(logic).toFinishAllListeners()
        expect(lastPostBody).toEqual({ max_reports_per_day: 5 })
        expect(logic.values.maxReportsPerDay).toBe(5)

        logic.actions.setDraftMaxReportsPerDay(null)
        logic.actions.saveDraftMaxReportsPerDay()
        await expectLogic(logic).toFinishAllListeners()
        expect(lastPostBody).toEqual({ max_reports_per_day: null })
        expect(logic.values.maxReportsPerDay).toBeNull()
    })

    it('keeps an unsaved daily limit draft when an unrelated setting is saved', async () => {
        await mountWith({})
        logic.actions.setDraftMaxReportsPerDay(7)
        // Saving a different field on this shared singleton logic must not re-anchor the draft.
        logic.actions.patchTeamConfig({ autostart_enabled: false })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.draftMaxReportsPerDay).toBe(7)
    })

    it('keeps an unsaved daily limit draft when an unrelated save fails and reloads', async () => {
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

        logic.actions.setDraftMaxReportsPerDay(7)
        // The failed patch triggers a reload; the reseed guard must not clobber the unsaved draft.
        logic.actions.patchTeamConfig({ autostart_enabled: false })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.draftMaxReportsPerDay).toBe(7)
    })

    it('refreshes the config when the user returns to the tab, without wiping the draft', async () => {
        let reportsToday = 3
        useMocks({
            get: {
                '/api/projects/:team_id/signals/config/': () => [
                    200,
                    {
                        id: 'cfg-1',
                        autostart_enabled: true,
                        default_autostart_priority: 'P4',
                        autostart_base_branches: {},
                        max_reports_per_day: 10,
                        reports_generated_today: reportsToday,
                    },
                ],
            },
        })
        initKeaTests()
        logic = signalTeamConfigLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.reportsGeneratedToday).toBe(3)

        logic.actions.setDraftMaxReportsPerDay(7)
        reportsToday = 9
        // jsdom's visibilityState is 'visible', so this dispatch is a return-to-tab.
        document.dispatchEvent(new Event('visibilitychange'))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.reportsGeneratedToday).toBe(9)
        // The reseed guard must hold for this reload path too, not just failure reloads.
        expect(logic.values.draftMaxReportsPerDay).toBe(7)
    })

    it('does not save the daily limit while a config request is in flight', async () => {
        let getCount = 0
        let resolveRefresh: (() => void) | undefined
        const postBodies: Partial<SignalTeamConfig>[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/signals/config/': async () => {
                    getCount += 1
                    if (getCount > 1) {
                        // Hold the refresh GET open so a save can land while it is in flight.
                        await new Promise<void>((resolve) => {
                            resolveRefresh = resolve
                        })
                    }
                    return [
                        200,
                        {
                            id: 'cfg-1',
                            autostart_enabled: true,
                            default_autostart_priority: 'P4',
                            autostart_base_branches: {},
                            max_reports_per_day: null,
                        },
                    ]
                },
            },
            post: {
                '/api/projects/:team_id/signals/config/': async ({ request }) => {
                    const body = (await request.json()) as Partial<SignalTeamConfig>
                    postBodies.push(body)
                    return [200, { id: 'cfg-1', autostart_enabled: true, default_autostart_priority: 'P4', ...body }]
                },
            },
        })
        initKeaTests()
        logic = signalTeamConfigLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        // Type a new limit, then a background refresh starts (jsdom's visibilityState is 'visible').
        logic.actions.setDraftMaxReportsPerDay(5)
        document.dispatchEvent(new Event('visibilitychange'))
        await waitFor(() => expect(logic.values.teamConfigLoading).toBe(true))
        // The draft differs from the saved value, so only the in-flight guard can block the save.
        expect(logic.values.saveMaxReportsPerDayDisabledReason).toBeNull()

        // Pressing Enter while the refresh GET is in flight must not fire a racing PATCH.
        logic.actions.saveDraftMaxReportsPerDay()
        expect(postBodies).toHaveLength(0)

        resolveRefresh?.()
        await expectLogic(logic).toFinishAllListeners()
    })

    it('throttles rapid tab-return refreshes to one request per window', async () => {
        let getCount = 0
        useMocks({
            get: {
                '/api/projects/:team_id/signals/config/': () => {
                    getCount += 1
                    return [
                        200,
                        {
                            id: 'cfg-1',
                            autostart_enabled: true,
                            default_autostart_priority: 'P4',
                            autostart_base_branches: {},
                        },
                    ]
                },
            },
        })
        initKeaTests()
        logic = signalTeamConfigLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(getCount).toBe(1)

        // jsdom's visibilityState is 'visible', so each dispatch is a return-to-tab.
        document.dispatchEvent(new Event('visibilitychange'))
        await expectLogic(logic).toFinishAllListeners()
        expect(getCount).toBe(2)

        // A second return within the throttle window must not fire another GET.
        document.dispatchEvent(new Event('visibilitychange'))
        await expectLogic(logic).toFinishAllListeners()
        expect(getCount).toBe(2)
    })

    it('stays out of the updating state during a background tab-return refresh', async () => {
        let getCount = 0
        let resolveRefresh: (() => void) | undefined
        useMocks({
            get: {
                '/api/projects/:team_id/signals/config/': async () => {
                    getCount += 1
                    if (getCount > 1) {
                        // Hold the refresh GET open so its in-flight state can be observed.
                        await new Promise<void>((resolve) => {
                            resolveRefresh = resolve
                        })
                    }
                    return [
                        200,
                        {
                            id: 'cfg-1',
                            autostart_enabled: true,
                            default_autostart_priority: 'P4',
                            autostart_base_branches: {},
                        },
                    ]
                },
            },
        })
        initKeaTests()
        logic = signalTeamConfigLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        // jsdom's visibilityState is 'visible', so this dispatch is a return-to-tab.
        document.dispatchEvent(new Event('visibilitychange'))
        // The refresh GET is now in flight, but it is a load, not a save, so the controls stay enabled.
        await waitFor(() => expect(logic.values.teamConfigLoading).toBe(true))
        expect(logic.values.teamConfigUpdating).toBe(false)

        resolveRefresh?.()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.teamConfigUpdating).toBe(false)
    })

    it('treats a cleared (NaN) daily limit input as unlimited', async () => {
        await mountWith({})
        logic.actions.setDraftMaxReportsPerDay(5)
        logic.actions.saveDraftMaxReportsPerDay()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.maxReportsPerDay).toBe(5)

        // A cleared number LemonInput emits NaN; it must reset the draft to null, not disable Save.
        logic.actions.setDraftMaxReportsPerDay(Number.NaN)
        expect(logic.values.draftMaxReportsPerDay).toBeNull()
        expect(logic.values.saveMaxReportsPerDayDisabledReason).toBeNull()
        logic.actions.saveDraftMaxReportsPerDay()
        await expectLogic(logic).toFinishAllListeners()
        expect(lastPostBody).toEqual({ max_reports_per_day: null })
        expect(logic.values.maxReportsPerDay).toBeNull()
    })

    it('blocks saving an invalid or unchanged daily report limit draft', async () => {
        await mountWith({})
        // Loading anchored the draft to the server value, so there is nothing to save yet.
        expect(logic.values.saveMaxReportsPerDayDisabledReason).toBe('No changes to save')
        logic.actions.setDraftMaxReportsPerDay(0)
        expect(logic.values.saveMaxReportsPerDayDisabledReason).toBe('Enter a whole number of at least 1')
        logic.actions.saveDraftMaxReportsPerDay()
        await expectLogic(logic).toFinishAllListeners()
        expect(lastPostBody).toBeNull()
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
