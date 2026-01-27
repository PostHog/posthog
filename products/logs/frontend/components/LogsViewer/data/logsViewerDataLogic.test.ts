import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { LogMessage } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator } from '~/types'

import { logsViewerDataLogic } from './logsViewerDataLogic'

// Mock posthog.capture before the mock
const mockPosthogCapture = jest.fn()

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    lemonToast: {
        error: jest.fn(),
    },
}))

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: {
        capture: (...args: any[]) => mockPosthogCapture(...args),
        captureException: jest.fn(),
        init: jest.fn(),
    },
}))

describe('logsViewerDataLogic', () => {
    let logic: ReturnType<typeof logsViewerDataLogic.build>

    const mockLogMessage: LogMessage = {
        uuid: 'log-1',
        timestamp: '2024-01-01T00:00:00Z',
        level: 'info',
        body: 'Test log message',
        attributes: {},
        trace_id: '',
        span_id: '',
        observed_timestamp: '',
        severity_text: 'error',
        severity_number: 0,
        resource_attributes: undefined,
        instrumentation_scope: '',
        event_name: '',
    }

    beforeEach(async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/logs/query/': () => [
                    200,
                    { results: [mockLogMessage], hasMore: true, nextCursor: 'cursor-123' },
                ],
            },
        })
        initKeaTests()
        logic = logsViewerDataLogic({ id: 'test-viewer' })
        logic.mount()
        mockPosthogCapture.mockClear()
        ;(lemonToast.error as jest.Mock).mockClear()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('fetchLogs', () => {
        it('fetches logs and updates state', async () => {
            await expectLogic(logic, () => {
                logic.actions.fetchLogs({
                    limit: 250,
                    orderBy: 'latest',
                    dateRange: { date_from: '-1h', date_to: null },
                    searchTerm: '',
                    filterGroup: { type: FilterLogicalOperator.And, values: [] },
                    severityLevels: [],
                    serviceNames: [],
                })
            })
                .toDispatchActions(['fetchLogs', 'fetchLogsSuccess'])
                .toMatchValues({
                    logs: [mockLogMessage],
                    hasMoreLogsToLoad: true,
                    nextCursor: 'cursor-123',
                    logsLoading: false,
                })
        })

        it('stores lastFetchPayload for pagination', async () => {
            const payload = {
                limit: 250,
                orderBy: 'latest' as const,
                dateRange: { date_from: '-1h', date_to: null },
                searchTerm: 'test',
                filterGroup: { type: FilterLogicalOperator.And, values: [] },
                severityLevels: ['error' as const],
                serviceNames: ['api'],
            }

            await expectLogic(logic, () => {
                logic.actions.fetchLogs(payload)
            })
                .toFinishAllListeners()
                .toMatchValues({
                    lastFetchPayload: payload,
                })
        })

        it('tracks analytics on success', async () => {
            const payload = {
                limit: 250,
                orderBy: 'latest' as const,
                dateRange: { date_from: '-1h', date_to: null },
                searchTerm: 'test',
                filterGroup: { type: FilterLogicalOperator.And, values: [] },
                severityLevels: [],
                serviceNames: [],
            }

            await expectLogic(logic, () => {
                logic.actions.fetchLogs(payload)
            }).toFinishAllListeners()

            expect(mockPosthogCapture).toHaveBeenCalledWith('logs results returned', {
                count: 1,
                query: payload,
            })
        })

        it('tracks analytics when no results returned', async () => {
            useMocks({
                post: {
                    '/api/environments/:team_id/logs/query/': () => [200, { results: [], hasMore: false }],
                },
            })

            const payload = {
                limit: 250,
                orderBy: 'latest' as const,
                dateRange: { date_from: '-1h', date_to: null },
                searchTerm: '',
                filterGroup: { type: FilterLogicalOperator.And, values: [] },
                severityLevels: [],
                serviceNames: [],
            }

            await expectLogic(logic, () => {
                logic.actions.fetchLogs(payload)
            }).toFinishAllListeners()

            expect(mockPosthogCapture).toHaveBeenCalledWith('logs no results returned', {
                query: payload,
            })
        })
    })

    describe('fetchNextPage', () => {
        beforeEach(async () => {
            // First, do an initial fetch to set up lastFetchPayload and nextCursor
            await expectLogic(logic, () => {
                logic.actions.fetchLogs({
                    limit: 250,
                    orderBy: 'latest',
                    dateRange: { date_from: '-1h', date_to: null },
                    searchTerm: '',
                    filterGroup: { type: FilterLogicalOperator.And, values: [] },
                    severityLevels: [],
                    serviceNames: [],
                })
            }).toFinishAllListeners()

            jest.clearAllMocks()
        })

        it('fetches next page and appends results', async () => {
            const newLogMessage: LogMessage = {
                uuid: 'log-2',
                timestamp: '2024-01-01T00:00:01Z',
                level: 'warn',
                body: 'Second log message',
                attributes: {},
                trace_id: '',
                span_id: '',
                observed_timestamp: '',
                severity_text: 'error',
                severity_number: 0,
                resource_attributes: undefined,
                instrumentation_scope: '',
                event_name: '',
            }

            useMocks({
                post: {
                    '/api/environments/:team_id/logs/query/': () => [
                        200,
                        { results: [newLogMessage], hasMore: false, nextCursor: null },
                    ],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.fetchNextPage()
            })
                .toDispatchActions(['fetchNextPage', 'fetchNextPageSuccess'])
                .toMatchValues({
                    logs: [mockLogMessage, newLogMessage],
                    hasMoreLogsToLoad: false,
                    nextCursor: null,
                })
        })

        it('tracks pagination analytics with query context', async () => {
            await expectLogic(logic, () => {
                logic.actions.fetchNextPage()
            }).toFinishAllListeners()

            expect(mockPosthogCapture).toHaveBeenCalledWith('logs load more requested', {
                query: logic.values.lastFetchPayload,
            })
        })

        it('does nothing when no cursor available', async () => {
            logic.actions.setNextCursor(null)

            await expectLogic(logic, () => {
                logic.actions.fetchNextPage()
            })
                .toDispatchActions(['fetchNextPage', 'fetchNextPageSuccess'])
                .toMatchValues({
                    logs: [mockLogMessage], // Unchanged
                })
        })

        it('does nothing when no lastFetchPayload available', async () => {
            // Create new logic instance without initial fetch
            const freshLogic = logsViewerDataLogic({ id: 'fresh-viewer' })
            freshLogic.mount()

            await expectLogic(freshLogic, () => {
                freshLogic.actions.fetchNextPage()
            })
                .toDispatchActions(['fetchNextPage', 'fetchNextPageSuccess'])
                .toMatchValues({
                    logs: [],
                })

            freshLogic.unmount()
        })
    })

    describe('error handling', () => {
        beforeEach(() => {
            ;(lemonToast.error as jest.Mock).mockClear()
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
        ])('suppresses fetchNextPage error "%s" (%s)', async (error) => {
            logic.actions.fetchNextPageFailure(error)
            await expectLogic(logic).toFinishAllListeners()

            expect(lemonToast.error).not.toHaveBeenCalled()
        })

        it('shows toast for legitimate fetchNextPage error', async () => {
            logic.actions.fetchNextPageFailure('Network error')
            await expectLogic(logic).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Failed to load more logs: Network error')
        })
    })

    describe('state management', () => {
        it('clearLogs resets state', async () => {
            // First fetch some logs
            await expectLogic(logic, () => {
                logic.actions.fetchLogs({
                    limit: 250,
                    orderBy: 'latest',
                    dateRange: { date_from: '-1h', date_to: null },
                    searchTerm: '',
                    filterGroup: { type: FilterLogicalOperator.And, values: [] },
                    severityLevels: [],
                    serviceNames: [],
                })
            }).toFinishAllListeners()

            expect(logic.values.logs.length).toBe(1)

            await expectLogic(logic, () => {
                logic.actions.clearLogs()
            }).toMatchValues({
                logs: [],
                hasMoreLogsToLoad: true,
                nextCursor: null,
            })
        })

        it('truncateLogs limits array length', async () => {
            const logs: LogMessage[] = Array.from({ length: 10 }, (_, i) => ({
                uuid: `log-${i}`,
                timestamp: `2024-01-01T00:00:${String(i).padStart(2, '0')}Z`,
                level: 'info',
                body: `Log ${i}`,
                attributes: {},
                trace_id: '',
                span_id: '',
                observed_timestamp: '',
                severity_text: 'error',
                severity_number: 0,
                resource_attributes: undefined,
                instrumentation_scope: '',
                event_name: '',
            }))

            logic.actions.setLogs(logs)

            await expectLogic(logic, () => {
                logic.actions.truncateLogs(5)
            }).toMatchValues({
                logs: logs.slice(0, 5),
            })
        })

        it('setLogs replaces entire logs array', async () => {
            const newLogs: LogMessage[] = [
                {
                    uuid: 'new-log',
                    timestamp: '2024-01-01T00:00:00Z',
                    level: 'error',
                    body: 'New log',
                    attributes: {},
                    trace_id: '',
                    span_id: '',
                    observed_timestamp: '',
                    severity_text: 'error',
                    severity_number: 0,
                    resource_attributes: undefined,
                    instrumentation_scope: '',
                    event_name: '',
                },
            ]

            await expectLogic(logic, () => {
                logic.actions.setLogs(newLogs)
            }).toMatchValues({
                logs: newLogs,
            })
        })
    })

    describe('abort controller management', () => {
        it('cancels in-progress fetch when new fetch starts', async () => {
            const abortSpy = jest.fn()
            const mockController = {
                abort: abortSpy,
                signal: {} as AbortSignal,
            } as AbortController

            logic.actions.setLogsAbortController(mockController)

            logic.actions.cancelInProgressFetchLogs(new AbortController(), 'new query started')

            expect(abortSpy).toHaveBeenCalledWith('new query started')
        })

        it('calls cancelInProgressFetchLogs on unmount', async () => {
            const cancelSpy = jest.spyOn(logic.actions, 'cancelInProgressFetchLogs')
            const mockController = {
                abort: jest.fn(),
                signal: {} as AbortSignal,
            } as AbortController

            await expectLogic(logic, () => {
                logic.actions.setLogsAbortController(mockController)
            }).toFinishAllListeners()

            logic.unmount()

            expect(cancelSpy).toHaveBeenCalledWith(null, 'unmounting component')
        })
    })

    describe('logsLoading selector', () => {
        it('reflects loading state during fetch', async () => {
            expect(logic.values.logsLoading).toBe(false)

            const fetchPromise = expectLogic(logic, () => {
                logic.actions.fetchLogs({
                    limit: 250,
                    orderBy: 'latest',
                    dateRange: { date_from: '-1h', date_to: null },
                    searchTerm: '',
                    filterGroup: { type: FilterLogicalOperator.And, values: [] },
                    severityLevels: [],
                    serviceNames: [],
                })
            })

            // During the fetch, loading should be true
            await fetchPromise.toDispatchActions(['fetchLogs'])
            expect(logic.values.logsLoading).toBe(true)

            // After completion, loading should be false
            await fetchPromise.toFinishAllListeners()
            expect(logic.values.logsLoading).toBe(false)
        })
    })
})
