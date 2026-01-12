import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { LogMessage } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { logsLogic } from './logsLogic'

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    lemonToast: {
        error: jest.fn(),
    },
}))

const createMockLog = (uuid: string): LogMessage => ({
    uuid,
    trace_id: 'trace-1',
    span_id: 'span-1',
    body: `Log ${uuid}`,
    attributes: {},
    timestamp: '2024-01-01T00:00:00Z',
    observed_timestamp: '2024-01-01T00:00:00Z',
    severity_text: 'info',
    severity_number: 9,
    level: 'info',
    resource_attributes: {},
    instrumentation_scope: 'test',
    event_name: 'log',
})

describe('logsLogic', () => {
    let logic: ReturnType<typeof logsLogic.build>

    beforeEach(async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/logs/query/': () => [200, { results: [] }],
                '/api/environments/:team_id/logs/sparkline/': () => [200, []],
            },
        })
        initKeaTests()
        logic = logsLogic({ tabId: 'test-tab' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('keyboard navigation', () => {
        const mockLogs = [createMockLog('log-1'), createMockLog('log-2'), createMockLog('log-3')]

        describe('highlightNextLog', () => {
            it('highlights first log when none is highlighted', async () => {
                logic.actions.fetchLogsSuccess(mockLogs)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightNextLog()
                })
                    .toDispatchActions(['highlightNextLog', 'setHighlightedLogId'])
                    .toMatchValues({
                        highlightedLogId: 'log-1',
                    })
            })

            it('highlights next log in sequence', async () => {
                logic.actions.fetchLogsSuccess(mockLogs)
                logic.actions.setHighlightedLogId('log-1')
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightNextLog()
                })
                    .toDispatchActions(['highlightNextLog', 'setHighlightedLogId'])
                    .toMatchValues({
                        highlightedLogId: 'log-2',
                    })
            })

            it('loads more logs when at last log and more available', async () => {
                logic.actions.fetchLogsSuccess(mockLogs)
                logic.actions.setHighlightedLogId('log-3')
                logic.actions.setHasMoreLogsToLoad(true)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightNextLog()
                }).toDispatchActions(['highlightNextLog', 'fetchNextLogsPage'])
            })

            it('does nothing when at last log and no more to load', async () => {
                logic.actions.fetchLogsSuccess(mockLogs)
                logic.actions.setHighlightedLogId('log-3')
                logic.actions.setHasMoreLogsToLoad(false)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightNextLog()
                })
                    .toDispatchActions(['highlightNextLog'])
                    .toNotHaveDispatchedActions(['setHighlightedLogId', 'fetchNextLogsPage'])
            })

            it('does nothing when logs are empty', async () => {
                logic.actions.fetchLogsSuccess([])
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightNextLog()
                })
                    .toDispatchActions(['highlightNextLog'])
                    .toNotHaveDispatchedActions(['setHighlightedLogId'])
            })
        })

        describe('highlightPreviousLog', () => {
            it('highlights last log when none is highlighted', async () => {
                logic.actions.fetchLogsSuccess(mockLogs)
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightPreviousLog()
                })
                    .toDispatchActions(['highlightPreviousLog', 'setHighlightedLogId'])
                    .toMatchValues({
                        highlightedLogId: 'log-3',
                    })
            })

            it('highlights previous log in sequence', async () => {
                logic.actions.fetchLogsSuccess(mockLogs)
                logic.actions.setHighlightedLogId('log-2')
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightPreviousLog()
                })
                    .toDispatchActions(['highlightPreviousLog', 'setHighlightedLogId'])
                    .toMatchValues({
                        highlightedLogId: 'log-1',
                    })
            })

            it('does nothing when at first log', async () => {
                logic.actions.fetchLogsSuccess(mockLogs)
                logic.actions.setHighlightedLogId('log-1')
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightPreviousLog()
                })
                    .toDispatchActions(['highlightPreviousLog'])
                    .toNotHaveDispatchedActions(['setHighlightedLogId'])
            })

            it('does nothing when logs are empty', async () => {
                logic.actions.fetchLogsSuccess([])
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.highlightPreviousLog()
                })
                    .toDispatchActions(['highlightPreviousLog'])
                    .toNotHaveDispatchedActions(['setHighlightedLogId'])
            })
        })

        describe('toggleExpandLog', () => {
            it('expands a log when not expanded', async () => {
                await expectLogic(logic, () => {
                    logic.actions.toggleExpandLog('log-1')
                }).toDispatchActions(['toggleExpandLog'])

                expect(logic.values.expandedLogIds.has('log-1')).toBe(true)
            })

            it('collapses a log when already expanded', async () => {
                logic.actions.toggleExpandLog('log-1')
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.expandedLogIds.has('log-1')).toBe(true)

                await expectLogic(logic, () => {
                    logic.actions.toggleExpandLog('log-1')
                }).toDispatchActions(['toggleExpandLog'])

                expect(logic.values.expandedLogIds.has('log-1')).toBe(false)
            })

            it('supports multiple expanded logs', async () => {
                logic.actions.toggleExpandLog('log-1')
                logic.actions.toggleExpandLog('log-2')
                logic.actions.toggleExpandLog('log-3')
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.expandedLogIds.has('log-1')).toBe(true)
                expect(logic.values.expandedLogIds.has('log-2')).toBe(true)
                expect(logic.values.expandedLogIds.has('log-3')).toBe(true)

                logic.actions.toggleExpandLog('log-2')
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.expandedLogIds.has('log-1')).toBe(true)
                expect(logic.values.expandedLogIds.has('log-2')).toBe(false)
                expect(logic.values.expandedLogIds.has('log-3')).toBe(true)
            })
        })
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
        ])('suppresses error "%s" (%s)', async (error) => {
            logic.actions.fetchLogsFailure(error)
            await expectLogic(logic).toFinishAllListeners()

            expect(lemonToast.error).not.toHaveBeenCalled()
        })

        it.each([['Network error'], ['Server returned 500'], ['Timeout exceeded']])(
            'shows toast for legitimate error "%s"',
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
        })

        it('shows toast for legitimate fetchNextLogsPage error', async () => {
            logic.actions.fetchNextLogsPageFailure('Network error')
            await expectLogic(logic).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Failed to load more logs: Network error')
        })
    })

    describe('URL parameter parsing', () => {
        it.each([
            ['JSON string array', '["error","warn"]', ['error', 'warn']],
            ['single item JSON array', '["info"]', ['info']],
            ['empty JSON array', '[]', []],
        ])('parses severityLevels from %s', async (_, urlValue, expected) => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { severityLevels: urlValue })
            }).toFinishAllListeners()

            expect(logic.values.severityLevels).toEqual(expected)
        })

        it.each([
            ['JSON string array', '["my-service","other-service"]', ['my-service', 'other-service']],
            ['single item JSON array', '["api"]', ['api']],
        ])('parses serviceNames from %s', async (_, urlValue, expected) => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { serviceNames: urlValue })
            }).toFinishAllListeners()

            expect(logic.values.serviceNames).toEqual(expected)
        })

        it('filters out malformed JSON as invalid severity level', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { severityLevels: 'not-valid-json[' })
            }).toFinishAllListeners()

            // parseTagsFilter falls back to comma-separated parsing, then validation filters invalid levels
            expect(logic.values.severityLevels).toEqual([])
        })

        it('filters out non-array JSON as invalid severity level', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { severityLevels: '"just-a-string"' })
            }).toFinishAllListeners()

            // parseTagsFilter falls back to comma-separated parsing, then validation filters invalid levels
            expect(logic.values.severityLevels).toEqual([])
        })

        it('handles comma-separated values via parseTagsFilter', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { severityLevels: 'error,warn,info' })
            }).toFinishAllListeners()

            expect(logic.values.severityLevels).toEqual(['error', 'warn', 'info'])
        })

        it.each([
            ['completely invalid value', '["invalid-level"]', []],
            ['typo in valid level', '["debug123"]', []],
            ['mix of valid and invalid', '["error","not-a-level","warn"]', ['error', 'warn']],
            ['invalid comma-separated', 'invalid,also-invalid', []],
        ])('filters out invalid severity levels (%s)', async (_, urlValue, expected) => {
            await expectLogic(logic, () => {
                router.actions.push('/logs', { severityLevels: urlValue })
            }).toFinishAllListeners()

            expect(logic.values.severityLevels).toEqual(expected)
        })
    })
})
