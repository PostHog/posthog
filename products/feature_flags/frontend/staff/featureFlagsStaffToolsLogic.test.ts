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
                '/api/feature_flags_staff_cache/warm_run': { run: null },
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

    describe('warm-all run status', () => {
        const WARM_RUN = {
            run_id: 'run-1',
            state: 'running',
            scope: 'teams_with_flags',
            total: 100,
            processed: 40,
            successful: 39,
            failed: 1,
            last_team_id: 4321,
            started_at: '2026-07-09T00:00:00+00:00',
            updated_at: '2026-07-09T00:10:00+00:00',
            is_stale: false,
            cancel_requested: false,
        }

        it('unwraps the run from the status endpoint response', async () => {
            // Let the mount-time load (mocked as { run: null }) settle first so the
            // assertion below unambiguously matches the reload with the new mock.
            await expectLogic(logic).toDispatchActions(['loadWarmRunSuccess'])
            useMocks({ get: { '/api/feature_flags_staff_cache/warm_run': { run: WARM_RUN } } })

            await expectLogic(logic, () => {
                logic.actions.loadWarmRun()
            })
                .toDispatchActions(['loadWarmRun', 'loadWarmRunSuccess'])
                .toMatchValues({ warmRun: WARM_RUN })
        })

        it('reads an absent run as null, not as the wrapper object', async () => {
            logic.actions.loadWarmRun()
            await expectLogic(logic).toDispatchActions(['loadWarmRunSuccess']).toMatchValues({ warmRun: null })
        })

        it('refetches status after a cancel request so the UI reflects it promptly', async () => {
            useMocks({
                post: {
                    '/api/feature_flags_staff_cache/warm_run/cancel': { run_id: 'run-1', cancel_requested: true },
                },
            })

            logic.actions.cancelWarmRun()
            await expectLogic(logic).toDispatchActions(['cancelWarmRunSuccess', 'loadWarmRun'])
            expect(lemonToast.success).toHaveBeenCalled()
        })

        it('shows an error toast when the cancel request fails', async () => {
            useMocks({ post: { '/api/feature_flags_staff_cache/warm_run/cancel': () => [400, {}] } })

            logic.actions.cancelWarmRun()
            await expectLogic(logic).toDispatchActions(['cancelWarmRunFailure'])
            expect(lemonToast.error).toHaveBeenCalled()
        })

        it('polls at the active cadence while a run is live, and falls back to idle otherwise', async () => {
            // Let the mount-time load (mocked as { run: null }, idle cadence) settle first.
            await expectLogic(logic).toDispatchActions(['loadWarmRunSuccess'])

            useMocks({ get: { '/api/feature_flags_staff_cache/warm_run': { run: WARM_RUN } } })
            logic.actions.loadWarmRun()
            await expectLogic(logic).toDispatchActions(['loadWarmRunSuccess'])
            expect(logic.cache.warmRunPollMs).toEqual(5000)

            // A stale "running" run is treated as idle, same as a completed/cancelled one.
            useMocks({ get: { '/api/feature_flags_staff_cache/warm_run': { run: { ...WARM_RUN, is_stale: true } } } })
            logic.actions.loadWarmRun()
            await expectLogic(logic).toDispatchActions(['loadWarmRunSuccess'])
            expect(logic.cache.warmRunPollMs).toEqual(30000)
        })

        it('falls back to the idle poll cadence when a status fetch fails', async () => {
            // Let the mount-time load (mocked as { run: null }) settle first so it can't race
            // with the loads below.
            await expectLogic(logic).toDispatchActions(['loadWarmRunSuccess'])

            // Put the poller into the active cadence first, so a no-op failure handler would be
            // observable (staying at 5000) instead of masked by the idle default from mount.
            useMocks({ get: { '/api/feature_flags_staff_cache/warm_run': { run: WARM_RUN } } })
            logic.actions.loadWarmRun()
            await expectLogic(logic).toDispatchActions(['loadWarmRunSuccess'])
            expect(logic.cache.warmRunPollMs).toEqual(5000)

            useMocks({ get: { '/api/feature_flags_staff_cache/warm_run': () => [500, {}] } })
            logic.actions.loadWarmRun()
            await expectLogic(logic).toDispatchActions(['loadWarmRunFailure'])
            expect(logic.cache.warmRunPollMs).toEqual(30000)
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

    describe('team config', () => {
        const TEAM_CONFIG_URL = '/api/feature_flags_staff_team_config'
        const SET_URL = '/api/feature_flags_staff_team_config/set'

        it('loads team config alongside cache status when the team selection changes', async () => {
            useMocks({
                get: { [TEAM_CONFIG_URL]: { results: [{ team_id: 5, minimal_flag_called_events: true }] } },
            })

            logic.actions.setSelectedTeamIds([5])
            await expectLogic(logic).toDispatchActionsInAnyOrder([
                'loadCacheStatus',
                'loadTeamConfig',
                'loadTeamConfigSuccess',
            ])
            await expectLogic(logic).toMatchValues({
                teamConfigByTeamId: { 5: { team_id: 5, minimal_flag_called_events: true } },
            })
        })

        it('setMinimalFlagCalledEvents updates teamConfigByTeamId and shows a success toast', async () => {
            useMocks({
                get: { [TEAM_CONFIG_URL]: { results: [{ team_id: 5, minimal_flag_called_events: false }] } },
                post: { [SET_URL]: { team_id: 5, minimal_flag_called_events: true } },
            })

            // The switch only renders once its row has loaded, so seed the selection first —
            // the mutation reducer patches an existing row in place, it doesn't add a new one.
            logic.actions.setSelectedTeamIds([5])
            await expectLogic(logic).toDispatchActions(['loadTeamConfigSuccess'])

            logic.actions.setMinimalFlagCalledEvents(5, true)
            // setMinimalFlagCalledEvents is a plain listener (not kea-loaders), since the
            // auto-generated Failure action wouldn't carry the team_id needed to clear the
            // right row's pending state on failure. teamConfigMutationSucceeded/Settled are the
            // actions it dispatches instead of the usual Success/Failure pair.
            await expectLogic(logic).toDispatchActions(['teamConfigMutationSucceeded', 'teamConfigMutationSettled'])

            expect(lemonToast.success).toHaveBeenCalled()
            await expectLogic(logic).toMatchValues({
                pendingTeamConfigTeamIds: [],
                teamConfigByTeamId: { 5: { team_id: 5, minimal_flag_called_events: true } },
            })
        })

        it('shows an error toast and leaves the value unchanged on failure', async () => {
            useMocks({
                get: { [TEAM_CONFIG_URL]: { results: [{ team_id: 5, minimal_flag_called_events: false }] } },
                post: { [SET_URL]: () => [500, {}] },
            })

            // Seed a known-good value first so a no-op failure is verifiably "unchanged", not just
            // absent. loadTeamConfig() alone would no-op: the loader bails out when
            // selectedTeamIds is empty, so the selection must be set first.
            logic.actions.setSelectedTeamIds([5])
            await expectLogic(logic).toDispatchActions(['loadTeamConfigSuccess'])

            logic.actions.setMinimalFlagCalledEvents(5, true)
            // No teamConfigMutationSucceeded on failure — only the settle action fires, clearing
            // the pending row.
            await expectLogic(logic).toDispatchActions(['teamConfigMutationSettled'])

            expect(lemonToast.error).toHaveBeenCalled()
            await expectLogic(logic).toMatchValues({
                pendingTeamConfigTeamIds: [],
                teamConfigByTeamId: { 5: { team_id: 5, minimal_flag_called_events: false } },
            })
        })

        it('only sends one mutation request when double-submitted for the same team', async () => {
            const handleSet = jest.fn(() => [200, { team_id: 5, minimal_flag_called_events: true }])
            useMocks({ post: { [SET_URL]: handleSet } })

            // Both dispatches happen before either mocked request resolves, exercising the
            // double-submit guard rather than two sequential, already-settled calls.
            await expectLogic(logic, () => {
                logic.actions.setMinimalFlagCalledEvents(5, true)
                logic.actions.setMinimalFlagCalledEvents(5, true)
            }).toFinishAllListeners()

            expect(handleSet).toHaveBeenCalledTimes(1)
        })
    })
})
