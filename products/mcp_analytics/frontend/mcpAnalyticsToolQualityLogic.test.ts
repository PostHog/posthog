import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { formatMsAsSeconds } from './dashboard/formatters'
import { type DailyToolStat, buildDailyChartData, mcpAnalyticsToolQualityLogic } from './mcpAnalyticsToolQualityLogic'

jest.mock('lib/api')
jest.mock('~/queries/query', () => ({
    hogqlQuery: jest.fn().mockResolvedValue({ results: [] }),
}))

const mockApi = api as jest.Mocked<typeof api>

function dailyStat(overrides: Partial<DailyToolStat> & { day: string }): DailyToolStat {
    return { calls: 0, errors: 0, p50: 0, p95: 0, p99: 0, ...overrides }
}

describe('mcpAnalyticsToolQualityLogic', () => {
    describe('buildDailyChartData', () => {
        it('fills missing days so the x-axis stays linear', () => {
            const data = buildDailyChartData([
                dailyStat({ day: '2026-06-05', calls: 100, errors: 10, p50: 200, p95: 900, p99: 2100 }),
                dailyStat({ day: '2026-06-07', calls: 50, errors: 0, p50: 150, p95: 800, p99: 1500 }),
            ])
            expect(data.labels).toEqual(['2026-06-05', '2026-06-06', '2026-06-07'])
            expect(data.calls).toEqual([100, 0, 50])
            expect(data.errors).toEqual([10, 0, 0])
            // Gap days get NaN (skipped by the chart), not a dip to zero.
            expect(data.successRate[0]).toBeCloseTo(90)
            expect(data.successRate[1]).toBeNaN()
            expect(data.p99).toEqual([2100, NaN, 1500])
        })

        it('returns empty series for no rows', () => {
            expect(buildDailyChartData([]).labels).toEqual([])
        })

        it('spans the full range when given one, zero-filling days outside the data', () => {
            const data = buildDailyChartData(
                [dailyStat({ day: '2026-06-07', calls: 50, errors: 0, p50: 150, p95: 800, p99: 1500 })],
                { start: '2026-06-05', end: '2026-06-08' }
            )
            expect(data.labels).toEqual(['2026-06-05', '2026-06-06', '2026-06-07', '2026-06-08'])
            expect(data.calls).toEqual([0, 0, 50, 0])
            expect(data.successRate[0]).toBeNaN()
            expect(data.successRate[2]).toBeCloseTo(100)
        })

        it('zero-fills the whole range when there is no data at all', () => {
            const data = buildDailyChartData([], { start: '2026-06-05', end: '2026-06-07' })
            expect(data.labels).toEqual(['2026-06-05', '2026-06-06', '2026-06-07'])
            expect(data.calls).toEqual([0, 0, 0])
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

    describe('date range and tool filters', () => {
        beforeEach(() => {
            jest.clearAllMocks()
            initKeaTests()
            jest.spyOn(mockApi, 'query').mockResolvedValue({ results: [] })
        })

        function queryCallsSince(callIndex: number): { query: string; filters: Record<string, any> }[] {
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
            expect(newCalls.map((call) => call.filters.dateRange)).toEqual([
                { date_from: '-30d', date_to: null },
                { date_from: '-30d', date_to: null },
                { date_from: '-30d', date_to: null },
            ])
        })

        it('reloads daily stats with the tool as a property filter when a tool is selected', async () => {
            const logic = mcpAnalyticsToolQualityLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const callsBefore = mockApi.query.mock.calls.length

            await expectLogic(logic, () => {
                logic.actions.setSelectedTool("evil'); DROP TABLE events; --")
            }).toFinishAllListeners()

            const newCalls = queryCallsSince(callsBefore)
            expect(newCalls.length).toBe(1) // daily stats only
            expect(newCalls[0].filters.properties).toEqual([
                expect.objectContaining({
                    key: '$mcp_tool_name',
                    value: ["evil'); DROP TABLE events; --"],
                    operator: 'exact',
                    type: 'event',
                }),
            ])
            // The tool value must never be interpolated into the HogQL string.
            expect(newCalls[0].query).not.toContain('DROP TABLE')
        })

        // Tool-quality row tuple as returned by the query (tool, calls, errors, then unused cols)
        const toolRowResult = (tool: string): unknown[] => [tool, 1, 0, 0, 0, 0, 0, 0, 0, '', '']

        it('clears the selected tool when a reload no longer includes it', async () => {
            mockApi.query.mockResolvedValue({ results: [toolRowResult('tool_a')] })
            const logic = mcpAnalyticsToolQualityLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setSelectedTool('tool_a')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.selectedTool).toBe('tool_a')

            mockApi.query.mockResolvedValue({ results: [toolRowResult('tool_b')] })
            await expectLogic(logic, () => {
                logic.actions.setSelectedCategories(['some-category'])
            }).toFinishAllListeners()

            expect(logic.values.selectedTool).toBeNull()
        })

        it('keeps the selected tool when a reload still includes it', async () => {
            mockApi.query.mockResolvedValue({ results: [toolRowResult('tool_a'), toolRowResult('tool_b')] })
            const logic = mcpAnalyticsToolQualityLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setSelectedTool('tool_a')
            await expectLogic(logic, () => {
                logic.actions.setSelectedCategories(['some-category'])
            }).toFinishAllListeners()

            expect(logic.values.selectedTool).toBe('tool_a')
        })
    })
})
