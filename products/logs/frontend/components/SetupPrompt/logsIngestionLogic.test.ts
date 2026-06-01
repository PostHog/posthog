import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { logsIngestionLogic } from './logsIngestionLogic'

describe('logsIngestionLogic', () => {
    let logic: ReturnType<typeof logsIngestionLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        localStorage.clear()
    })

    describe('loadTeamHasLogs', () => {
        it('loads teamHasLogs as true when logs exist', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/logs/has_logs/': () => [200, { hasLogs: true }],
                },
            })

            logic = logsIngestionLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadTeamHasLogs', 'loadTeamHasLogsSuccess']).toMatchValues({
                teamHasLogs: true,
                teamHasLogsLoading: false,
                teamHasLogsCheckFailed: false,
            })
        })

        it('loads teamHasLogs as false when no logs exist', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/logs/has_logs/': () => [200, { hasLogs: false }],
                },
            })

            logic = logsIngestionLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadTeamHasLogs', 'loadTeamHasLogsSuccess']).toMatchValues({
                teamHasLogs: false,
                teamHasLogsLoading: false,
                teamHasLogsCheckFailed: false,
            })
        })

        it('handles API failure and sets teamHasLogsCheckFailed', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/logs/has_logs/': () => [500, { detail: 'Server error' }],
                },
            })

            logic = logsIngestionLogic()
            logic.mount()

            // With retry logic (3 attempts), this will eventually fail
            await expectLogic(logic).toDispatchActions(['loadTeamHasLogs', 'loadTeamHasLogsFailure']).toMatchValues({
                teamHasLogs: null, // kea-loaders sets to null on failure
                teamHasLogsLoading: false,
                teamHasLogsCheckFailed: true,
            })
        })

        it('starts with loading state on mount', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/logs/has_logs/': () => [200, { hasLogs: true }],
                },
            })

            logic = logsIngestionLogic()
            logic.mount()

            // Immediately after mount, the loader should be in loading state
            expect(logic.values.teamHasLogsLoading).toBe(true)

            await expectLogic(logic).toDispatchActions(['loadTeamHasLogsSuccess'])
        })

        it('resets teamHasLogsCheckFailed on new load attempt', async () => {
            let callCount = 0
            useMocks({
                get: {
                    '/api/environments/:team_id/logs/has_logs/': () => {
                        callCount++
                        if (callCount <= 3) {
                            return [500, { detail: 'Server error' }]
                        }
                        return [200, { hasLogs: true }]
                    },
                },
            })

            logic = logsIngestionLogic()
            logic.mount()

            // First attempt fails after retries
            await expectLogic(logic).toDispatchActions(['loadTeamHasLogs', 'loadTeamHasLogsFailure']).toMatchValues({
                teamHasLogsCheckFailed: true,
            })

            // Manual retry succeeds
            logic.actions.loadTeamHasLogs()

            await expectLogic(logic).toDispatchActions(['loadTeamHasLogs', 'loadTeamHasLogsSuccess']).toMatchValues({
                teamHasLogs: true,
                teamHasLogsCheckFailed: false,
            })
        })
    })

    describe('caching', () => {
        it('skips API call when cachedTeamHasLogs is true', async () => {
            const mockFn = jest.fn(() => [200, { hasLogs: true }])
            useMocks({
                get: { '/api/environments/:team_id/logs/has_logs/': mockFn },
            })

            logic = logsIngestionLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadTeamHasLogs', 'loadTeamHasLogsSuccess'])
            expect(mockFn).toHaveBeenCalledTimes(1)

            logic.unmount()

            // Mount again - should skip API call due to cache
            logic = logsIngestionLogic()
            logic.mount()

            await expectLogic(logic).toNotHaveDispatchedActions(['loadTeamHasLogs'])
            expect(mockFn).toHaveBeenCalledTimes(1)
            expect(logic.values.hasLogs).toBe(true)
        })

        it('makes API call when cachedTeamHasLogs is null', async () => {
            const mockFn = jest.fn(() => [200, { hasLogs: false }])
            useMocks({
                get: { '/api/environments/:team_id/logs/has_logs/': mockFn },
            })

            logic = logsIngestionLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadTeamHasLogs', 'loadTeamHasLogsSuccess'])
            expect(mockFn).toHaveBeenCalledTimes(1)

            logic.unmount()

            // Mount again - should make API call since false is not cached
            logic = logsIngestionLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadTeamHasLogs', 'loadTeamHasLogsSuccess'])
            expect(mockFn).toHaveBeenCalledTimes(2)
        })

        it('hasLogs selector falls back to cachedTeamHasLogs when teamHasLogs is undefined', async () => {
            useMocks({
                get: { '/api/environments/:team_id/logs/has_logs/': () => [200, { hasLogs: true }] },
            })

            logic = logsIngestionLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadTeamHasLogsSuccess'])
            expect(logic.values.cachedTeamHasLogs).toBe(true)

            logic.unmount()

            // Remount - teamHasLogs starts undefined, hasLogs should use cached
            logic = logsIngestionLogic()
            logic.mount()

            expect(logic.values.teamHasLogs).toBeFalsy()
            expect(logic.values.hasLogs).toBe(true)
        })
    })
})
