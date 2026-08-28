import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { formatMsAsSeconds } from './dashboard/formatters'
import { type DailyToolStat, buildDailyChartData, mcpAnalyticsToolQualityLogic } from './mcpAnalyticsToolQualityLogic'

jest.mock('lib/api')
jest.mock('~/queries/query', () => ({
    hogqlQuery: jest.fn().mockResolvedValue({ results: [] }),
}))

const mockApi = api as jest.Mocked<typeof api>

const emptyToolRowsResponse = { results: [], totalCount: 0 }

function dailyStat(overrides: Partial<DailyToolStat> & { day: string }): DailyToolStat {
    return { calls: 0, errors: 0, p50: 0, p95: 0, p99: 0, ...overrides }
}

describe('mcpAnalyticsToolQualityLogic', () => {
    describe('buildDailyChartData', () => {
        it('projects rows onto the bucket keys, zero/NaN-filling gaps', () => {
            const data = buildDailyChartData(
                [
                    dailyStat({ day: '2026-06-05', calls: 100, errors: 10, p50: 200, p95: 900, p99: 2100 }),
                    dailyStat({ day: '2026-06-07', calls: 50, errors: 0, p50: 150, p95: 800, p99: 1500 }),
                ],
                ['2026-06-05 00:00:00', '2026-06-06 00:00:00', '2026-06-07 00:00:00']
            )
            expect(data.labels).toEqual(['2026-06-05 00:00:00', '2026-06-06 00:00:00', '2026-06-07 00:00:00'])
            expect(data.calls).toEqual([100, 0, 50])
            expect(data.errors).toEqual([10, 0, 0])
            // Gap buckets get NaN (skipped by the chart), not a dip to zero.
            expect(data.successRate[0]).toBeCloseTo(90)
            expect(data.successRate[1]).toBeNaN()
            expect(data.p99).toEqual([2100, NaN, 1500])
        })

        it('returns empty series for empty bucket keys', () => {
            expect(buildDailyChartData([], []).labels).toEqual([])
        })

        // Sub-day windows bucket by hour: rows keyed to an hour must line up with hourly keys, so the
        // "12 hours collapses to a single point" bug can't come back.
        it('lines up hourly rows with hourly bucket keys', () => {
            const data = buildDailyChartData(
                [dailyStat({ day: '2026-06-07 10:00:00', calls: 12, errors: 3, p50: 80, p95: 200, p99: 400 })],
                ['2026-06-07 09:00:00', '2026-06-07 10:00:00', '2026-06-07 11:00:00']
            )
            expect(data.calls).toEqual([0, 12, 0])
            expect(data.errors).toEqual([0, 3, 0])
            expect(data.successRate[1]).toBeCloseTo(75)
        })
    })

    describe('formatMsAsSeconds', () => {
        it.each([
            [0, '0'],
            [50, '50ms'],
            [500, '0.5s'],
            [1000, '1s'],
            [99, '99ms'],
            [100, '0.1s'],
            [1500, '1.5s'],
            [2000, '2s'],
            [NaN, '—'],
            [Infinity, '—'],
        ])('formats %s ms as %s', (input, expected) => {
            expect(formatMsAsSeconds(input)).toBe(expected)
        })
    })

    describe('incompleteTail', () => {
        beforeEach(() => {
            jest.clearAllMocks()
            initKeaTests()
            jest.spyOn(mockApi, 'query').mockImplementation(async (query: any) =>
                query.kind === NodeKind.MCPToolQualityRowsQuery ? emptyToolRowsResponse : { results: [] }
            )
        })

        // An open-ended relative window always ends in the bucket that is still collecting, and a
        // window that closed in the past never does, so this holds whenever the suite runs.
        it.each([
            ['an open-ended window', '-7d', null, true],
            ['a window that already closed', '2026-06-01', '2026-06-10', false],
        ])('is %s: %s', async (_label, dateFrom, dateTo, expected) => {
            const logic = mcpAnalyticsToolQualityLogic()
            logic.mount()
            await expectLogic(logic, () => {
                logic.actions.setDateFilter(dateFrom, dateTo)
            }).toFinishAllListeners()

            expect(logic.values.incompleteTail).toBe(expected)
        })
    })

    describe('date range and tool filters', () => {
        beforeEach(() => {
            jest.clearAllMocks()
            initKeaTests()
            jest.spyOn(mockApi, 'query').mockImplementation(async (query: any) =>
                query.kind === NodeKind.MCPToolQualityRowsQuery ? emptyToolRowsResponse : { results: [] }
            )
        })

        function queryCallsSince(callIndex: number): Record<string, any>[] {
            return mockApi.query.mock.calls.slice(callIndex).map((call) => call[0] as any)
        }

        it('reloads the tool rows, daily stats and category counts with the new date range when the date filter changes', async () => {
            const logic = mcpAnalyticsToolQualityLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const callsBefore = mockApi.query.mock.calls.length

            await expectLogic(logic, () => {
                logic.actions.setDateFilter('-30d', null)
            }).toFinishAllListeners()

            const newCalls = queryCallsSince(callsBefore)
            expect(newCalls.length).toBe(3) // tool rows + daily stats + category counts
            // The scope-share headline must track the same window as the rest of the tab.
            expect(newCalls.map((call) => call.dateRange)).toEqual([
                { date_from: '-30d', date_to: null },
                { date_from: '-30d', date_to: null },
                { date_from: '-30d', date_to: null },
            ])
        })

        it('reloads daily stats scoped to the tool when one is selected, passing it as a typed param', async () => {
            const logic = mcpAnalyticsToolQualityLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const callsBefore = mockApi.query.mock.calls.length

            await expectLogic(logic, () => {
                logic.actions.setSelectedTool("evil'); DROP TABLE events; --")
            }).toFinishAllListeners()

            const newCalls = queryCallsSince(callsBefore)
            expect(newCalls.length).toBe(1) // daily stats only
            // The tool rides as a typed toolName param (the runner binds it as a constant), never as raw SQL.
            expect(newCalls[0].toolName).toBe("evil'); DROP TABLE events; --")
            expect(newCalls[0].query).toBeUndefined()
        })

        // Tool-quality row item as returned by the runner.
        const toolRowResult = (tool: string): Record<string, unknown> => ({
            tool,
            total_calls: 1,
            errors: 0,
            error_rate_pct: 0,
            p50_duration_ms: 0,
            p95_duration_ms: 0,
            p99_duration_ms: 0,
            users: 0,
            sessions: 0,
            first_seen: '',
            last_seen: '',
        })

        it('clears the selected tool when the category scope changes', async () => {
            mockApi.query.mockImplementation(async (query: any) =>
                query.kind === NodeKind.MCPToolQualityRowsQuery
                    ? { ...emptyToolRowsResponse, results: [toolRowResult('tool_a')], totalCount: 1 }
                    : { results: [] }
            )
            const logic = mcpAnalyticsToolQualityLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setSelectedTool('tool_a')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.selectedTool).toBe('tool_a')

            await expectLogic(logic, () => {
                logic.actions.setSelectedCategories(['some-category'])
            }).toFinishAllListeners()

            expect(logic.values.selectedTool).toBeNull()
        })

        it('keeps the selected tool while searching, sorting, or changing pages', async () => {
            mockApi.query.mockImplementation(async (query: any) =>
                query.kind === NodeKind.MCPToolQualityRowsQuery
                    ? { ...emptyToolRowsResponse, results: [toolRowResult('tool_b')], totalCount: 100 }
                    : { results: [] }
            )
            const logic = mcpAnalyticsToolQualityLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setSelectedTool('tool_a')
            await expectLogic(logic, () => {
                logic.actions.setToolQualityPageIndex(1)
                logic.actions.setSearchTerm('tool_b')
                logic.actions.setToolQualitySort('error_rate_pct', 'DESC')
            }).toFinishAllListeners()

            expect(logic.values.selectedTool).toBe('tool_a')
        })

        it('sends search, global sort, and page offsets to the rows query', async () => {
            mockApi.query.mockImplementation(async (query: any) =>
                query.kind === NodeKind.MCPToolQualityRowsQuery
                    ? { ...emptyToolRowsResponse, results: [toolRowResult('tool_a')], totalCount: 151 }
                    : { results: [] }
            )
            const logic = mcpAnalyticsToolQualityLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            let callsBefore = mockApi.query.mock.calls.length
            await expectLogic(logic, () => {
                logic.actions.setToolQualityPageIndex(2)
            }).toFinishAllListeners()
            let rowsQuery = queryCallsSince(callsBefore).find(
                (query) => query.kind === NodeKind.MCPToolQualityRowsQuery
            )
            expect(rowsQuery).toMatchObject({ limit: 50, offset: 100 })

            callsBefore = mockApi.query.mock.calls.length
            await expectLogic(logic, () => {
                logic.actions.setSearchTerm('needle')
            }).toFinishAllListeners()
            rowsQuery = queryCallsSince(callsBefore).find((query) => query.kind === NodeKind.MCPToolQualityRowsQuery)
            expect(logic.values.toolQualityPageIndex).toBe(0)
            expect(rowsQuery).toMatchObject({ search: 'needle', limit: 50, offset: 0 })

            callsBefore = mockApi.query.mock.calls.length
            await expectLogic(logic, () => {
                logic.actions.setToolQualitySort('error_rate_pct', 'ASC')
            }).toFinishAllListeners()
            rowsQuery = queryCallsSince(callsBefore).find((query) => query.kind === NodeKind.MCPToolQualityRowsQuery)
            expect(rowsQuery).toMatchObject({ sortColumn: 'error_rate_pct', sortDirection: 'ASC', offset: 0 })
        })

        it('refetches the charts at the picked grouping, leaving the table alone', async () => {
            const logic = mcpAnalyticsToolQualityLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const callsBefore = mockApi.query.mock.calls.length

            await expectLogic(logic, () => {
                logic.actions.setPinnedInterval('hour')
            }).toFinishAllListeners()

            const newCalls = queryCallsSince(callsBefore)
            expect(newCalls.length).toBe(1) // daily stats only — the table is a single-window aggregate
            expect(newCalls[0].interval).toBe('hour')
        })

        // The two filters are independent: changing the window must not silently undo the grouping.
        it('keeps the picked grouping when the date range changes', async () => {
            const logic = mcpAnalyticsToolQualityLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setPinnedInterval('hour')
            await expectLogic(logic, () => {
                logic.actions.setDateFilter('-14d', null)
            }).toFinishAllListeners()

            // Two weeks would auto-group by day.
            expect(logic.values.interval).toBe('hour')
        })
    })
})
