import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { logsViewerConfigLogic } from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { logsViewerDataLogic, shouldSkipFilterGroupChange } from './logsViewerDataLogic'

// Shared helpers for building filter groups in tests
const makeFilter = (
    key: string,
    value: string[] | null,
    filterType: PropertyFilterType = PropertyFilterType.LogAttribute
): any => ({
    key,
    value,
    operator: PropertyOperator.Exact,
    type: filterType,
})

const makeFilterGroup = (...filters: any[]): any => ({
    type: FilterLogicalOperator.And,
    values: [{ type: FilterLogicalOperator.And, values: filters }],
})

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

    describe('live-tail identity', () => {
        const makeLog = (uuid: string, timestamp: string): any => ({
            uuid,
            timestamp,
            body: `body of ${uuid}`,
            attributes: { service: 'api' },
            severity_text: 'info',
        })

        it('keeps existing log and parsed row references across a live-tail poll', async () => {
            // The poll used to rebuild every log ({...log, new: false}) and parsedLogs re-cloned
            // them all again, so every visible row's identity churned per 1-5s tick and the whole
            // virtualized list re-rendered. Only genuinely new rows may get fresh references.
            const existingA = makeLog('log-a', '2026-01-02T00:00:00Z')
            const existingB = makeLog('log-b', '2026-01-01T00:00:00Z')
            logic.actions.setLogs([existingA, existingB])
            const parsedBefore = logic.values.parsedLogs

            useMocks({
                post: {
                    '/api/environments/:team_id/logs/query/': () => [
                        200,
                        {
                            // The poll window overlaps: one genuinely new row plus repeats.
                            results: [
                                makeLog('log-c', '2026-01-03T00:00:00Z'),
                                makeLog('log-a', '2026-01-02T00:00:00Z'),
                                makeLog('log-b', '2026-01-01T00:00:00Z'),
                            ],
                            maxExportableLogs: 5000,
                        },
                    ],
                },
            })
            logic.actions.setLiveTailRunning(true)
            await expectLogic(logic).toFinishAllListeners()

            const logByUuid = (uuid: string): any => logic.values.logs.find((log) => log.uuid === uuid)
            expect(logic.values.logs).toHaveLength(3)
            expect(logByUuid('log-a')).toBe(existingA)
            expect(logByUuid('log-b')).toBe(existingB)

            const parsedByUuid = (list: typeof parsedBefore, uuid: string): any => list.find((log) => log.uuid === uuid)
            expect(parsedByUuid(logic.values.parsedLogs, 'log-a')).toBe(parsedByUuid(parsedBefore, 'log-a'))
            expect(parsedByUuid(logic.values.parsedLogs, 'log-b')).toBe(parsedByUuid(parsedBefore, 'log-b'))

            // Only the fresh batch is highlighted; the next poll replaces the set.
            expect([...logic.values.newLogUuids]).toEqual(['log-c'])
        })

        it('clears the arrival highlight when a fresh query result set lands', async () => {
            logic.actions.setNewLogUuids(['log-a'])
            logic.actions.fetchLogs()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.newLogUuids.size).toBe(0)
        })
    })

    describe('sparklineData selector', () => {
        it.each([
            ['null', null, { labels: [], dates: [], data: [] }],
            ['an empty array', [], { labels: [], dates: [], data: [] }],
            [
                'valid data',
                [
                    { time: '2024-01-01T00:00:00Z', severity: 'info', count: 5 },
                    { time: '2024-01-01T00:01:00Z', severity: 'error', count: 3 },
                ],
                { labels: expect.any(Array), dates: expect.any(Array), data: expect.any(Array) },
            ],
        ])('returns correct data when sparkline is %s', async (_, sparklineInput, expected) => {
            logic.actions.setSparkline(sparklineInput as any[] | null)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.sparklineData).toEqual(expected)
        })
    })

    describe('totalLogsMatchingFilters selector', () => {
        it.each([
            ['null', null, 0],
            [
                'valid data',
                [
                    { time: '2024-01-01T00:00:00Z', severity: 'info', count: 5 },
                    { time: '2024-01-01T00:00:00Z', severity: 'error', count: 3 },
                ],
                8,
            ],
        ])('returns correct total when sparkline is %s', async (_, sparklineInput, expected) => {
            logic.actions.setSparkline(sparklineInput as any[] | null)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.totalLogsMatchingFilters).toEqual(expected)
        })
    })

    describe('sparklineIncompleteBarIndices selector', () => {
        // 60s buckets ending at 00:02:00; last bucket start = 00:02:00.
        const buckets = [
            { time: '2024-01-01T00:00:00Z', severity: 'info', count: 5 },
            { time: '2024-01-01T00:01:00Z', severity: 'info', count: 3 },
            { time: '2024-01-01T00:02:00Z', severity: 'info', count: 2 },
        ]
        // Same buckets but the trailing three are empty.
        const emptyTailBuckets = [
            { time: '2024-01-01T00:00:00Z', severity: 'info', count: 5 },
            { time: '2024-01-01T00:01:00Z', severity: 'info', count: 0 },
            { time: '2024-01-01T00:02:00Z', severity: 'info', count: 0 },
            { time: '2024-01-01T00:03:00Z', severity: 'info', count: 0 },
        ]

        it.each([
            ['checkpoint is null', buckets, null, []],
            ['there are fewer than two buckets', buckets.slice(0, 1), '2024-01-01T00:00:30Z', []],
            ['the checkpoint has caught up to the latest bar', buckets, '2024-01-01T00:01:50Z', []],
            ['the checkpoint lags the latest bucket start by a quarter bar', buckets, '2024-01-01T00:01:30Z', [1, 2]],
            ['more than two empty buckets lag — only the latest bar', emptyTailBuckets, '2024-01-01T00:01:00Z', [3]],
            [
                'more than two buckets lag but one has data — all of them',
                [
                    { time: '2024-01-01T00:00:00Z', severity: 'info', count: 5 },
                    { time: '2024-01-01T00:01:00Z', severity: 'info', count: 0 },
                    { time: '2024-01-01T00:02:00Z', severity: 'info', count: 1 },
                    { time: '2024-01-01T00:03:00Z', severity: 'info', count: 0 },
                ],
                '2024-01-01T00:01:00Z',
                [1, 2, 3],
            ],
        ])('returns the right indices when %s', async (_, sparklineInput, checkpoint, expected) => {
            logic.actions.setSparkline(sparklineInput as any[])
            logic.actions.setLiveLogsCheckpoint(checkpoint)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.sparklineIncompleteBarIndices).toEqual(expected)
        })

        it('clears the indices when a new query starts, until a fresh checkpoint lands', async () => {
            logic.actions.setSparkline(buckets as any[])
            logic.actions.setLiveLogsCheckpoint('2024-01-01T00:01:30Z')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.sparklineIncompleteBarIndices).toEqual([1, 2])

            logic.actions.clearLogs()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.sparklineIncompleteBarIndices).toEqual([])
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

    describe('auto-refetch on filter changes', () => {
        let filtersLogic: ReturnType<typeof logsViewerFiltersLogic.build>

        beforeEach(async () => {
            filtersLogic = logsViewerFiltersLogic({ id: 'test-tab' })
            filtersLogic.mount()

            // Run initial query so hasRunQuery is true
            logic.actions.runQuery()
            await expectLogic(logic).toFinishAllListeners()
        })

        afterEach(() => {
            filtersLogic.unmount()
        })

        it.each([
            ['setSearchTerm', 'error message'],
            ['setDateRange', { date_from: '-24h', date_to: null }],
            ['setSeverityLevels', ['error', 'warn']],
            ['setServiceNames', ['api-server']],
        ])('%s triggers runQuery', async (action, value) => {
            await expectLogic(logic, () => {
                ;(filtersLogic.actions as any)[action](value)
            }).toDispatchActions(['handleQueryChange', 'runQuery'])
        })

        it('setFilters triggers runQuery', async () => {
            await expectLogic(logic, () => {
                filtersLogic.actions.setFilters({ searchTerm: 'new search' })
            }).toDispatchActions(['handleQueryChange', 'runQuery'])
        })

        it('setOrderBy triggers runQuery', async () => {
            const configLogic = logsViewerConfigLogic({ id: 'test-tab' })
            configLogic.mount()
            await expectLogic(logic, () => {
                configLogic.actions.setOrderBy('earliest')
            }).toDispatchActions(['runQuery'])
            configLogic.unmount()
        })

        it('adding an empty filter does not trigger runQuery', async () => {
            jest.clearAllMocks()
            filtersLogic.actions.setFilterGroup(
                makeFilterGroup(makeFilter('service.name', null, PropertyFilterType.LogResourceAttribute)),
                true
            )
            await expectLogic(logic).toFinishAllListeners()

            expect(posthog.capture).not.toHaveBeenCalledWith(
                'logs filter changed',
                expect.objectContaining({ filter_type: 'attributes' })
            )
        })

        it('completing a filter value triggers runQuery', async () => {
            filtersLogic.actions.setFilterGroup(
                makeFilterGroup(makeFilter('service.name', null, PropertyFilterType.LogResourceAttribute)),
                true
            )
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                filtersLogic.actions.setFilterGroup(
                    makeFilterGroup(
                        makeFilter('service.name', ['api-server'], PropertyFilterType.LogResourceAttribute)
                    ),
                    false
                )
            }).toDispatchActions(['handleQueryChange', 'runQuery'])
        })

        it('editing a filter while another is empty still triggers runQuery', async () => {
            filtersLogic.actions.setFilterGroup(
                makeFilterGroup(
                    makeFilter('service.name', ['api-server'], PropertyFilterType.LogResourceAttribute),
                    makeFilter('host', null, PropertyFilterType.LogAttribute)
                ),
                true
            )
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                filtersLogic.actions.setFilterGroup(
                    makeFilterGroup(
                        makeFilter('service.name', ['worker'], PropertyFilterType.LogResourceAttribute),
                        makeFilter('host', null, PropertyFilterType.LogAttribute)
                    ),
                    false
                )
            }).toDispatchActions(['handleQueryChange', 'runQuery'])
        })
    })
})

describe('shouldSkipFilterGroupChange', () => {
    const emptyGroup = makeFilterGroup()

    it.each([
        ['no previous value', emptyGroup, undefined, true],
        [
            'values are deep equal',
            makeFilterGroup(makeFilter('host', ['web-1'])),
            makeFilterGroup(makeFilter('host', ['web-1'])),
            true,
        ],
        ['new empty filter added', makeFilterGroup(makeFilter('host', null)), emptyGroup, true],
        [
            'filter value completed',
            makeFilterGroup(makeFilter('host', ['web-1'])),
            makeFilterGroup(makeFilter('host', null)),
            false,
        ],
        [
            'filter edited (same count)',
            makeFilterGroup(makeFilter('host', ['web-2'])),
            makeFilterGroup(makeFilter('host', ['web-1'])),
            false,
        ],
        [
            'edit while another empty (same count)',
            makeFilterGroup(makeFilter('host', ['web-2']), makeFilter('env', null)),
            makeFilterGroup(makeFilter('host', ['web-1']), makeFilter('env', null)),
            false,
        ],
        [
            'filter removed',
            makeFilterGroup(makeFilter('host', ['web-1'])),
            makeFilterGroup(makeFilter('host', ['web-1']), makeFilter('env', ['prod'])),
            false,
        ],
    ])('%s → %s', (_, current, previous, expected) => {
        expect(shouldSkipFilterGroupChange(current, previous)).toBe(expected)
    })
})
