import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

import {
    aggregateHarnessRows,
    type BucketRow,
    buildKPIs,
    buildKpiWindow,
    buildToolDailySeries,
    categorizeHarness,
    deltaPct,
    type HarnessRawRow,
    mcpDashboardOverviewLogic,
    pickNotableSessions,
    type SessionRow,
    type ToolDailyRow,
} from './mcpDashboardOverviewLogic'

jest.mock('lib/api')
jest.mock('./generated/api', () => ({
    mcpAnalyticsIntentClustersRetrieve: jest.fn().mockResolvedValue({ status: 'idle', clusters: [] }),
    mcpAnalyticsIntentClustersRecompute: jest.fn(),
}))

const mockApi = api as jest.Mocked<typeof api>

function session(overrides: Partial<SessionRow> & { session_id: string }): SessionRow {
    return {
        tool_calls: 0,
        errors: 0,
        error_rate_pct: 0,
        duration_seconds: 0,
        distinct_tools: 0,
        last_seen: '',
        ...overrides,
    }
}

describe('mcpDashboardOverviewLogic', () => {
    describe('categorizeHarness', () => {
        it.each([
            ['claude-code/1.0.0', 'Claude Code'],
            ['claude-ai', 'Claude.ai'],
            ['anthropic/claudeai', 'Claude.ai'],
            ['cursor/0.42', 'Cursor'],
            ['codex-cli', 'OpenAI Codex'],
            ['visual studio code', 'VS Code'],
            ['something-nobody-knows', 'Other'],
            ['', 'Other'],
        ])('maps %s -> %s', (raw, expected) => {
            expect(categorizeHarness(raw)).toBe(expected)
        })

        it('strips the "(via mcp-remote …)" suffix before matching', () => {
            expect(categorizeHarness('claude-code (via mcp-remote 1.2.3)')).toBe('Claude Code')
        })
    })

    describe('deltaPct', () => {
        it.each([
            [150, 100, 50],
            [50, 100, -50],
            [0, 0, 0],
            [100, 0, null],
        ])('deltaPct(%s, %s) = %s', (current, previous, expected) => {
            expect(deltaPct(current, previous)).toBe(expected)
        })
    })

    describe('aggregateHarnessRows', () => {
        it('folds raw clients into categories, sums counts, and sorts by volume', () => {
            const raw: HarnessRawRow[] = [
                { client: 'claude-code/1.0', total_calls: 100, errors: 10, sessions: 5 },
                { client: 'claude-code/2.0', total_calls: 50, errors: 5, sessions: 3 },
                { client: 'cursor/0.4', total_calls: 40, errors: 0, sessions: 2 },
            ]
            const result = aggregateHarnessRows(raw)
            expect(result).toHaveLength(2)
            expect(result[0]).toEqual({
                category: 'Claude Code',
                total_calls: 150,
                errors: 15,
                error_rate_pct: 10,
                sessions: 8,
                raw_clients: ['claude-code/1.0', 'claude-code/2.0'],
            })
            expect(result[1]).toMatchObject({ category: 'Cursor', total_calls: 40, error_rate_pct: 0 })
        })
    })

    describe('buildToolDailySeries', () => {
        it('pivots flat rows into sorted day labels and per-tool series ordered by volume', () => {
            const rows: ToolDailyRow[] = [
                { day: '2024-01-02', tool: 'a', calls: 5 },
                { day: '2024-01-01', tool: 'a', calls: 3 },
                { day: '2024-01-01', tool: 'b', calls: 10 },
            ]
            expect(buildToolDailySeries(rows)).toEqual({
                labels: ['2024-01-01', '2024-01-02'],
                tools: [
                    { tool: 'b', data: [10, 0] },
                    { tool: 'a', data: [3, 5] },
                ],
            })
        })

        it('keeps the top 8 tools and folds the rest into a single "Other" series', () => {
            // 10 tools on one day, each with a distinct volume (tool-0 busiest … tool-9 quietest).
            const rows: ToolDailyRow[] = Array.from({ length: 10 }, (_, i) => ({
                day: '2024-01-01',
                tool: `tool-${i}`,
                calls: 100 - i,
            }))
            const { tools } = buildToolDailySeries(rows)
            expect(tools).toHaveLength(9) // 8 named + Other
            expect(tools.slice(0, 8).map((t) => t.tool)).toEqual([
                'tool-0',
                'tool-1',
                'tool-2',
                'tool-3',
                'tool-4',
                'tool-5',
                'tool-6',
                'tool-7',
            ])
            // Other = tool-8 (92) + tool-9 (91)
            expect(tools[8]).toEqual({ tool: 'Other', data: [183] })
        })
    })

    describe('buildKpiWindow', () => {
        it.each([
            ['2024-01-08', '2024-01-15', '2024-01-08', '2024-01-01', 14],
            ['2024-01-01', '2024-01-31', '2024-01-01', '2023-12-02', 60],
        ])(
            'doubles the [%s, %s] window back to %s with cutoff at the selected start',
            (dateFrom, dateTo, expectedCutoff, expectedPriorStart, expectedSpanDays) => {
                const window = buildKpiWindow({ dateFrom, dateTo }, 'UTC')
                expect(window.currentStartDay).toBe(expectedCutoff)
                expect(dayjs(window.dateFrom).format('YYYY-MM-DD')).toBe(expectedPriorStart)
                expect(dayjs(window.dateTo).diff(dayjs(window.dateFrom), 'day')).toBe(expectedSpanDays)
            }
        )
    })

    describe('buildKPIs', () => {
        it('splits current vs prior buckets and computes values, deltas, and sparklines', () => {
            const rows: BucketRow[] = [
                { bucket: '2024-01-09', sessions: 20, tool_calls: 200, errors: 15, p95: 300 },
                { bucket: '2024-01-08', sessions: 10, tool_calls: 100, errors: 5, p95: 200 },
                { bucket: '2024-01-01', sessions: 5, tool_calls: 50, errors: 5, p95: 150 },
            ]
            const kpis = buildKPIs(rows, '2024-01-08')

            expect(kpis.sessions).toEqual({
                value: 30,
                previousValue: 5,
                deltaPct: 500,
                sparkline: [10, 20], // current sorted by bucket
                goodDirection: 'up',
            })
            expect(kpis.toolCalls).toMatchObject({
                value: 300,
                previousValue: 50,
                deltaPct: 500,
                sparkline: [100, 200],
            })
            expect(kpis.p95LatencyMs).toMatchObject({
                value: 300,
                previousValue: 150,
                deltaPct: 100,
                goodDirection: 'down',
            })
            expect(kpis.errorRatePct.value).toBeCloseTo(6.667, 2)
            expect(kpis.errorRatePct.previousValue).toBeCloseTo(10, 5)
            expect(kpis.errorRatePct.goodDirection).toBe('down')
        })

        it('returns null deltas when there is no prior-period data', () => {
            const rows: BucketRow[] = [{ bucket: '2024-01-08', sessions: 10, tool_calls: 100, errors: 0, p95: 200 }]
            expect(buildKPIs(rows, '2024-01-08').sessions.deltaPct).toBeNull()
        })
    })

    describe('pickNotableSessions', () => {
        it('returns nothing for an empty set', () => {
            expect(pickNotableSessions([])).toEqual([])
        })

        it('picks one session per rule, then tops up with the busiest, capped and deduped', () => {
            const rows: SessionRow[] = [
                session({
                    session_id: 'A',
                    tool_calls: 20,
                    errors: 10,
                    error_rate_pct: 50,
                    duration_seconds: 100,
                    distinct_tools: 2,
                }),
                session({
                    session_id: 'B',
                    tool_calls: 5,
                    errors: 5,
                    error_rate_pct: 100,
                    duration_seconds: 30,
                    distinct_tools: 1,
                }),
                session({
                    session_id: 'C',
                    tool_calls: 8,
                    errors: 1,
                    error_rate_pct: 12,
                    duration_seconds: 40,
                    distinct_tools: 9,
                }),
                session({
                    session_id: 'D',
                    tool_calls: 15,
                    errors: 0,
                    error_rate_pct: 0,
                    duration_seconds: 5,
                    distinct_tools: 3,
                }),
                session({
                    session_id: 'E',
                    tool_calls: 12,
                    errors: 1,
                    error_rate_pct: 8,
                    duration_seconds: 60,
                    distinct_tools: 2,
                }),
            ]
            const picked = pickNotableSessions(rows)
            expect(picked.map((p) => ({ id: p.session.session_id, rule: p.rule }))).toEqual([
                { id: 'A', rule: 'worst_error_rate' },
                { id: 'B', rule: 'all_fail' },
                { id: 'C', rule: 'most_exploratory' },
                { id: 'D', rule: 'exemplar' },
                { id: 'E', rule: 'high_activity' },
            ])
            // never more than the cap, never the same session twice
            expect(picked).toHaveLength(5)
            expect(new Set(picked.map((p) => p.session.session_id)).size).toBe(5)
        })
    })

    describe('date filter wiring', () => {
        beforeEach(() => {
            jest.clearAllMocks()
            initKeaTests()
            jest.spyOn(mockApi, 'query').mockResolvedValue({ results: [] } as any)
        })

        function reloadCallsSince(callIndex: number): { query: string; filters: Record<string, any> }[] {
            return mockApi.query.mock.calls.slice(callIndex).map((call) => call[0] as any)
        }

        it('reloads every tile when the date filter changes', async () => {
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const callsBefore = mockApi.query.mock.calls.length

            await expectLogic(logic, () => {
                logic.actions.setDateFilter('-30d', null)
            }).toFinishAllListeners()

            const reloads = reloadCallsSince(callsBefore)
            // Six tiles: KPI + the five breakdown queries.
            expect(reloads.length).toBe(6)
            // The five breakdowns pass the raw selected range straight through.
            const breakdowns = reloads.filter((call) => call.filters.dateRange.date_from === '-30d')
            expect(breakdowns).toHaveLength(5)
            // The KPI tile widens to an absolute doubled window so it can compare against the prior period.
            const kpi = reloads.find((call) => call.query.includes('AS bucket'))
            expect(kpi?.filters.dateRange.date_from).not.toBe('-30d')
            expect(dayjs(kpi?.filters.dateRange.date_from).isValid()).toBe(true)
        })
    })
})
