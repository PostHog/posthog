import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { featureFlagsStaffToolsLogic, StaffTeamResult } from './featureFlagsStaffToolsLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), warning: jest.fn(), error: jest.fn() },
}))

const TEAM: StaffTeamResult = {
    id: 5,
    name: 'Acme',
    api_token: 'phc_acme',
    organization_id: 'org-uuid',
    organization_name: 'Acme Org',
    project_id: 5,
}

describe('featureFlagsStaffToolsLogic', () => {
    let logic: ReturnType<typeof featureFlagsStaffToolsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        useMocks({
            get: {
                '/api/feature_flags_staff_teams': { results: [TEAM] },
                '/api/feature_flags_staff_cache': { results: [] },
            },
        })
        initKeaTests()
        logic = featureFlagsStaffToolsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('team-admin deep link', () => {
        it('seeds and resolves a team from the team-admin deep link', async () => {
            router.actions.push('/feature_flags/staff?team_id=5')
            await expectLogic(logic).toDispatchActions(['seedTeamFromDeepLink', 'searchTeams', 'searchTeamsSuccess'])
            await expectLogic(logic).toMatchValues({
                selectedTeamIds: [5],
                selectedTeams: [TEAM],
            })
        })

        it('loads cache status for the deep-linked team without a manual refresh', async () => {
            useMocks({
                get: {
                    '/api/feature_flags_staff_teams': { results: [TEAM] },
                    '/api/feature_flags_staff_cache': {
                        results: [
                            {
                                team_id: 5,
                                evaluation: { source: 'redis', flag_count: 3 },
                                definitions: { source: 'redis', flag_count: 3 },
                            },
                        ],
                    },
                },
            })

            router.actions.push('/feature_flags/staff?team_id=5')
            await expectLogic(logic).toDispatchActions(['seedTeamFromDeepLink', 'loadCacheStatusSuccess'])
            await expectLogic(logic).toMatchValues({
                cacheStatusByTeamId: {
                    5: {
                        team_id: 5,
                        evaluation: { source: 'redis', flag_count: 3 },
                        definitions: { source: 'redis', flag_count: 3 },
                    },
                },
            })
        })

        it('does not re-seed a team after it has been manually deselected', async () => {
            router.actions.push('/feature_flags/staff?team_id=5')
            await expectLogic(logic).toDispatchActions(['seedTeamFromDeepLink', 'searchTeamsSuccess'])

            logic.actions.setSelectedTeamIds([])
            // Simulates urlToAction re-running with the same URL, e.g. browser back/forward.
            router.actions.push('/feature_flags/staff?team_id=5')

            await expectLogic(logic).toMatchValues({ selectedTeamIds: [] })
        })
    })

    describe('cache mutations', () => {
        const MUTATION_CASES = [
            {
                label: 'rebuildCache',
                run: () => logic.actions.rebuildCache({ caches: ['evaluation'] }),
                url: '/api/feature_flags_staff_cache/rebuild',
                successAction: 'rebuildCacheSuccess',
                failureAction: 'rebuildCacheFailure',
            },
            {
                label: 'clearCache',
                run: () => logic.actions.clearCache({ caches: ['evaluation'] }),
                url: '/api/feature_flags_staff_cache/clear',
                successAction: 'clearCacheSuccess',
                failureAction: 'clearCacheFailure',
            },
        ]

        beforeEach(() => {
            logic.actions.setSelectedTeamIds([5])
        })

        it.each(MUTATION_CASES)(
            '$label shows a success toast and reloads status when nothing is missing',
            async ({ run, url, successAction }) => {
                useMocks({ post: { [url]: { not_found_team_ids: [] } } })

                run()
                await expectLogic(logic).toDispatchActions([successAction, 'loadCacheStatus'])
                expect(lemonToast.success).toHaveBeenCalled()
                expect(lemonToast.warning).not.toHaveBeenCalled()
            }
        )

        it.each(MUTATION_CASES)(
            '$label shows a warning toast when some team ids are not found',
            async ({ run, url, successAction }) => {
                useMocks({ post: { [url]: { not_found_team_ids: [999] } } })

                run()
                await expectLogic(logic).toDispatchActions([successAction, 'loadCacheStatus'])
                expect(lemonToast.warning).toHaveBeenCalled()
                expect(lemonToast.success).not.toHaveBeenCalled()
            }
        )

        it.each(MUTATION_CASES)('$label shows an error toast on failure', async ({ run, url, failureAction }) => {
            useMocks({ post: { [url]: () => [500, {}] } })

            run()
            await expectLogic(logic).toDispatchActions([failureAction])
            expect(lemonToast.error).toHaveBeenCalled()
        })
    })

    describe('cache entry viewer', () => {
        it('fetches the entry for the requested team and cache, keyed by team_id and cache', async () => {
            useMocks({
                get: {
                    '/api/feature_flags_staff_cache/entry': ({ request }) => {
                        const params = new URL(request.url).searchParams
                        return [
                            200,
                            {
                                team_id: Number(params.get('team_id')),
                                cache: params.get('cache'),
                                source: 'redis',
                                data: { flags: [] },
                            },
                        ]
                    },
                },
            })

            logic.actions.viewCacheEntry({ teamId: 5, cache: 'definitions' })
            await expectLogic(logic)
                .toDispatchActions(['viewCacheEntrySuccess'])
                .toMatchValues({
                    viewingCacheEntry: { teamId: 5, cache: 'definitions' },
                    cacheEntry: { team_id: 5, cache: 'definitions', source: 'redis', data: { flags: [] } },
                })
        })

        it('clears the viewed entry on close', async () => {
            useMocks({ get: { '/api/feature_flags_staff_cache/entry': { team_id: 5, cache: 'evaluation' } } })

            logic.actions.viewCacheEntry({ teamId: 5, cache: 'evaluation' })
            await expectLogic(logic).toDispatchActions(['viewCacheEntrySuccess'])

            logic.actions.closeCacheEntryModal()
            expectLogic(logic).toMatchValues({ viewingCacheEntry: null })
        })

        it('shows an error toast and closes the modal on failure', async () => {
            useMocks({ get: { '/api/feature_flags_staff_cache/entry': () => [404, {}] } })

            logic.actions.viewCacheEntry({ teamId: 5, cache: 'evaluation' })
            await expectLogic(logic).toDispatchActions(['viewCacheEntryFailure'])
            expect(lemonToast.error).toHaveBeenCalled()
            expectLogic(logic).toMatchValues({ viewingCacheEntry: null })
        })
    })

    describe('team search loader', () => {
        it('does not query below the minimum search length', async () => {
            logic.actions.searchTeams({ query: 'a' })
            await expectLogic(logic).toDispatchActions(['searchTeamsSuccess']).toMatchValues({ teamSearchResults: [] })
        })

        it('returns results and records display info for a real query', async () => {
            logic.actions.searchTeams({ query: 'Acme' })
            await expectLogic(logic)
                .toDispatchActions(['searchTeamsSuccess'])
                .toMatchValues({ teamSearchResults: [TEAM], knownTeams: { 5: TEAM } })
        })
    })
})
