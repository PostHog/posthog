import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { type DailyToolStat, buildDailyChartData, mcpAnalyticsToolDetailLogic } from './mcpAnalyticsToolDetailLogic'

jest.mock('lib/api')

const mockApi = api as jest.Mocked<typeof api>

function stat(overrides: Partial<DailyToolStat> & { day: string }): DailyToolStat {
    return {
        calls: 0,
        errors: 0,
        p50: 0,
        p95: 0,
        users: 0,
        sessions: 0,
        ...overrides,
    }
}

describe('buildDailyChartData', () => {
    it('returns empty series for no rows, so the empty state shows', () => {
        expect(buildDailyChartData([], ['2026-06-01 00:00:00'])).toEqual({
            labels: [],
            calls: [],
            errors: [],
            p50: [],
            p95: [],
            users: [],
            sessions: [],
        })
    })

    // Guards the "sparklines lose their line" regression: with one active day, projecting onto the
    // full window's day keys pads the axis out (counts→0, latency→NaN) so the line still renders.
    it('projects rows onto day bucket keys, padding empty days', () => {
        const rows = [stat({ day: '2026-06-03', calls: 5, errors: 0, p50: 50, p95: 150, users: 1, sessions: 1 })]
        const keys = ['2026-06-01 00:00:00', '2026-06-02 00:00:00', '2026-06-03 00:00:00', '2026-06-04 00:00:00']
        expect(buildDailyChartData(rows, keys)).toEqual({
            labels: keys,
            calls: [0, 0, 5, 0],
            errors: [0, 0, 0, 0],
            p50: [NaN, NaN, 50, NaN],
            p95: [NaN, NaN, 150, NaN],
            users: [0, 0, 1, 0],
            sessions: [0, 0, 1, 0],
        })
    })

    // Sub-day windows bucket by hour: hourly rows must line up with hourly keys, so "12 hours
    // collapses to a single point" can't come back.
    it('lines up hourly rows with hourly bucket keys', () => {
        const rows = [
            stat({ day: '2026-06-03 10:00:00', calls: 12, errors: 2, p50: 80, p95: 200, users: 4, sessions: 5 }),
        ]
        const keys = ['2026-06-03 09:00:00', '2026-06-03 10:00:00', '2026-06-03 11:00:00']
        const data = buildDailyChartData(rows, keys)
        expect(data.calls).toEqual([0, 12, 0])
        expect(data.p95).toEqual([NaN, 200, NaN])
        expect(data.sessions).toEqual([0, 5, 0])
    })
})

describe('failure drill-down', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        jest.spyOn(mockApi, 'query').mockResolvedValue({ results: [] })
    })

    // The occurrences query must receive the bucket's RAW parts (not the composed display
    // label), and the no-status bucket must omit errorStatus so the backend's
    // "only events without a status" branch applies.
    it.each([
        ['statused bucket', '500', '500'],
        ['no-status bucket', '', undefined],
    ])(
        'selecting a %s queries occurrences with raw bucket params and stores the results',
        async (_label, bucketStatus, expectedStatus) => {
            const logic = mcpAnalyticsToolDetailLogic({ toolName: 'query_run' })
            logic.mount()
            const occurrence = {
                timestamp: '2026-07-15 00:00:00',
                distinct_id: 'd1',
                session_id: 's1',
                harness: 'Claude Code',
                intent: '',
                error_message: 'boom: table not found',
                error_status: bucketStatus,
            }
            mockApi.query.mockClear()
            jest.spyOn(mockApi, 'query').mockResolvedValue({ results: [occurrence] })

            await expectLogic(logic, () => {
                logic.actions.selectFailure({
                    message: 'api_5xx (HTTP 500)',
                    error_type: 'api_5xx',
                    error_status: bucketStatus,
                    occurrences: 2,
                    last_seen: '2026-07-15 00:00:00',
                    harnesses: [],
                })
            }).toDispatchActions(['loadFailureOccurrences', 'loadFailureOccurrencesSuccess'])

            expect(mockApi.query).toHaveBeenCalledWith(
                expect.objectContaining({
                    kind: 'MCPToolFailureOccurrencesQuery',
                    toolName: 'query_run',
                    errorType: 'api_5xx',
                    errorStatus: expectedStatus,
                })
            )
            expect(logic.values.failureOccurrences).toEqual([occurrence])
        }
    )

    // Guards the stale-response race: bucket A selected, then bucket B before A resolves.
    // Without the loader breakpoint, A's late response would overwrite B's occurrences
    // while the modal header still shows B.
    it('discards a superseded bucket load so a slow earlier bucket cannot overwrite the latest one', async () => {
        const logic = mcpAnalyticsToolDetailLogic({ toolName: 'query_run' })
        logic.mount()
        const occurrenceFor = (id: string): Record<string, string> => ({
            timestamp: '2026-07-15 00:00:00',
            distinct_id: id,
            session_id: 's1',
            harness: 'Claude Code',
            intent: '',
            error_message: `boom from ${id}`,
            error_status: '',
        })
        let resolveSlowA: (value: unknown) => void = () => {}
        const slowA = new Promise((resolve) => {
            resolveSlowA = resolve
        })
        jest.spyOn(mockApi, 'query')
            .mockImplementationOnce(() => slowA as any)
            .mockImplementationOnce(() => Promise.resolve({ results: [occurrenceFor('bucketB')] }))

        const bucket = (errorType: string): any => ({
            message: errorType,
            error_type: errorType,
            error_status: '',
            occurrences: 1,
            last_seen: '2026-07-15 00:00:00',
            harnesses: [],
        })
        await expectLogic(logic, () => {
            logic.actions.selectFailure(bucket('api_5xx'))
            logic.actions.selectFailure(bucket('internal'))
        }).toDispatchActions(['loadFailureOccurrencesSuccess'])
        expect(logic.values.failureOccurrences).toEqual([occurrenceFor('bucketB')])

        // Bucket A's request resolves late — its stale result must be discarded.
        resolveSlowA({ results: [occurrenceFor('bucketA')] })
        await new Promise((resolve) => setTimeout(resolve, 0))
        expect(logic.values.failureOccurrences).toEqual([occurrenceFor('bucketB')])
    })

    it('clears the previous bucket occurrences when deselecting', async () => {
        const logic = mcpAnalyticsToolDetailLogic({ toolName: 'query_run' })
        logic.mount()
        jest.spyOn(mockApi, 'query').mockResolvedValue({
            results: [
                {
                    timestamp: '2026-07-15 00:00:00',
                    distinct_id: 'd1',
                    session_id: 's1',
                    harness: 'Claude Code',
                    intent: '',
                    error_message: 'boom',
                    error_status: '',
                },
            ],
        })

        await expectLogic(logic, () => {
            logic.actions.selectFailure({
                message: 'internal',
                error_type: 'internal',
                error_status: '',
                occurrences: 1,
                last_seen: '2026-07-15 00:00:00',
                harnesses: [],
            })
        }).toDispatchActions(['loadFailureOccurrencesSuccess'])

        await expectLogic(logic, () => {
            logic.actions.selectFailure(null)
        }).toMatchValues({ selectedFailure: null, failureOccurrences: [] })
    })
})
