import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { logsIngestionLogic } from './logsIngestionLogic'

describe('logsIngestionLogic', () => {
    let logic: ReturnType<typeof logsIngestionLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
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
})
