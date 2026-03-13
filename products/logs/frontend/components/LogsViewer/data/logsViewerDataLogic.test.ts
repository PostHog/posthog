import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { logsViewerDataLogic } from './logsViewerDataLogic'

jest.mock('posthog-js')
jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    lemonToast: {
        error: jest.fn(),
    },
}))

describe('logsViewerDataLogic', () => {
    let logic: ReturnType<typeof logsViewerDataLogic.build>

    beforeEach(async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/logs/query/': () => [200, { results: [], maxExportableLogs: 5000 }],
                '/api/environments/:team_id/logs/sparkline/': () => [200, []],
            },
        })
        initKeaTests()
        logic = logsViewerDataLogic({ id: 'test-tab' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('error handling', () => {
        beforeEach(() => {
            jest.clearAllMocks()
        })

        it.each([
            ['new query started', 'exact match for NEW_QUERY_STARTED_ERROR_MESSAGE'],
            ['Fetch is aborted', 'Safari abort message'],
            ['The operation was aborted', 'alternative abort message'],
            ['ABORTED', 'uppercase abort'],
            ['Request aborted by user', 'abort substring'],
        ])('suppresses fetchLogs error "%s" (%s)', async (error) => {
            logic.actions.fetchLogsFailure(error)
            await expectLogic(logic).toFinishAllListeners()

            expect(lemonToast.error).not.toHaveBeenCalled()
            expect(posthog.capture).not.toHaveBeenCalled()
        })

        it.each([['Network error'], ['Server returned 500'], ['Timeout exceeded']])(
            'shows toast for legitimate fetchLogs error "%s"',
            async (error) => {
                logic.actions.fetchLogsFailure(error)
                await expectLogic(logic).toFinishAllListeners()

                expect(lemonToast.error).toHaveBeenCalledWith(`Failed to load logs: ${error}`)
            }
        )

        it.each([
            ['Fetch is aborted', 'Safari abort message'],
            ['new query started', 'exact match for NEW_QUERY_STARTED_ERROR_MESSAGE'],
        ])('suppresses fetchNextLogsPage error "%s" (%s)', async (error) => {
            logic.actions.fetchNextLogsPageFailure(error)
            await expectLogic(logic).toFinishAllListeners()

            expect(lemonToast.error).not.toHaveBeenCalled()
            expect(posthog.capture).not.toHaveBeenCalled()
        })

        it('shows toast for legitimate fetchNextLogsPage error', async () => {
            logic.actions.fetchNextLogsPageFailure('Network error')
            await expectLogic(logic).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Failed to load more logs: Network error')
        })
    })

    describe('query failure event capture', () => {
        beforeEach(() => {
            jest.clearAllMocks()
        })

        it.each([
            ['fetchLogsFailure' as const, 'logs'],
            ['fetchNextLogsPageFailure' as const, 'logs_next_page'],
            ['fetchSparklineFailure' as const, 'sparkline'],
        ])('captures %s with query_type "%s"', async (action, expectedQueryType) => {
            logic.actions[action]('Some server error')
            await expectLogic(logic).toFinishAllListeners()

            expect(posthog.capture).toHaveBeenCalledWith('logs query failed', {
                query_type: expectedQueryType,
                error_type: 'unknown',
                status_code: null,
                error_message: 'Some server error',
            })
        })

        it.each([
            [{ status: 504, message: 'Gateway Timeout' }, 'timeout', 504],
            ['Query timed out', 'timeout', null],
            [{ status: 500, message: 'Internal Server Error' }, 'server_error', 500],
            [{ status: 429, message: 'Too Many Requests' }, 'rate_limited', 429],
            ['memory limit exceeded', 'out_of_memory', null],
        ])(
            'classifies error %j as error_type "%s" with status_code %s',
            async (errorObject, expectedType, expectedStatus) => {
                logic.actions.fetchLogsFailure(String(errorObject), errorObject)
                await expectLogic(logic).toFinishAllListeners()

                expect(posthog.capture).toHaveBeenCalledWith(
                    'logs query failed',
                    expect.objectContaining({
                        error_type: expectedType,
                        status_code: expectedStatus,
                    })
                )
            }
        )

        it.each([['new query started'], ['Fetch is aborted'], ['ABORTED']])(
            'does not capture event for user-initiated error "%s"',
            async (error) => {
                logic.actions.fetchLogsFailure(error)
                logic.actions.fetchNextLogsPageFailure(error)
                logic.actions.fetchSparklineFailure(error)
                await expectLogic(logic).toFinishAllListeners()

                expect(posthog.capture).not.toHaveBeenCalled()
            }
        )
    })
})
