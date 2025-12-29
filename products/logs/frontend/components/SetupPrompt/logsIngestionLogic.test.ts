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

    describe('loadHasLogs', () => {
        it('loads hasLogs as true when logs exist', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/logs/has_logs/': () => [200, { hasLogs: true }],
                },
            })

            logic = logsIngestionLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadHasLogs', 'loadHasLogsSuccess']).toMatchValues({
                hasLogs: true,
                hasLogsLoading: false,
            })
        })

        it('loads hasLogs as false when no logs exist', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/logs/has_logs/': () => [200, { hasLogs: false }],
                },
            })

            logic = logsIngestionLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadHasLogs', 'loadHasLogsSuccess']).toMatchValues({
                hasLogs: false,
                hasLogsLoading: false,
            })
        })

        it('handles API failure', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/logs/has_logs/': () => [500, { detail: 'Server error' }],
                },
            })

            logic = logsIngestionLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadHasLogs', 'loadHasLogsFailure']).toMatchValues({
                hasLogs: null, // kea-loaders sets to null on failure
                hasLogsLoading: false,
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
            expect(logic.values.hasLogsLoading).toBe(true)

            await expectLogic(logic).toDispatchActions(['loadHasLogsSuccess'])
        })
    })
})
