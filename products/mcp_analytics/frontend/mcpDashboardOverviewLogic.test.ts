import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { BUCKET_FORMAT } from 'lib/utils/timeBuckets'
import { urls } from 'scenes/urls'

import { MCPDashboardQuery, MCPDashboardSection } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { HARNESS_BY_LABEL, harnessMark } from './dashboard/harnessRegistry'
import {
    type ActivityRow,
    type BucketRow,
    buildDailyActivity,
    buildKPIs,
    rankToolsByErrorRate,
    buildToolDailySeries,
    deltaPct,
    mcpDashboardOverviewLogic,
    pickNotableSessions,
    type SessionRow,
    type ToolRow,
    type ToolDailyRow,
} from './mcpDashboardOverviewLogic'

jest.mock('lib/api')
jest.mock('./generated/api', () => ({
    mcpAnalyticsIntentClustersRetrieve: jest.fn().mockResolvedValue({ status: 'idle', clusters: [] }),
    mcpAnalyticsIntentClustersRecompute: jest.fn(),
}))

const mockApi = api as jest.Mocked<typeof api>

type Answer = unknown[] | Error

function mockSections(respond: (section: MCPDashboardSection) => Answer = () => []): void {
    mockApi.query.mockImplementation(async (node: any) => ({
        results: Object.fromEntries(
            (node as MCPDashboardQuery).sections.map((section) => {
                const answer = respond(section)
                return [section, answer instanceof Error ? { error: answer.message } : { results: answer }]
            })
        ),
    }))
}

function queriesSince(callIndex: number): MCPDashboardQuery[] {
    return mockApi.query.mock.calls.slice(callIndex).map((call) => call[0] as MCPDashboardQuery)
}

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
    describe('harnessMark', () => {
        // The expected labels mirror HARNESS_LABELS in mcp_harness.py, minus "Other".
        // If the backend renames or adds a label, update this list to keep it in sync
        // and add the corresponding entry to HARNESS_BY_LABEL in harnessRegistry.ts.
        const EXPECTED_HARNESS_LABELS = [
            'Claude Desktop',
            'Claude Code (VS Code)',
            'Claude Agent SDK',
            'Claude Code',
            'Claude.ai',
            'Anthropic API',
            'Cowork',
            'Claude Design',
            'ChatGPT',
            'OpenAI Agent Builder',
            'OpenAI Responses API',
            'OpenAI',
            'OpenAI Codex',
            'Grok',
            'Cursor',
            'VS Code',
            'Windsurf',
            'Replit',
            'Lovable',
            'Manus',
            'CodeRabbit',
            'Notion',
            'Linear',
            'LibreChat',
            'Pi',
            'Kimchi',
            'Antigravity',
            'Poke',
            'opencode',
            'Kiro',
            'Desktop Commander',
            'PostHog CLI',
        ]

        it.each(EXPECTED_HARNESS_LABELS)('HARNESS_BY_LABEL has an entry for backend label %s', (label) => {
            expect(Object.prototype.hasOwnProperty.call(HARNESS_BY_LABEL, label)).toBe(true)
        })

        it('HARNESS_BY_LABEL has no key the backend does not reserve', () => {
            // Mirrors MARKED_CLIENT_NAMES in mcp_harness.py. The backend rejects custom harness names
            // in both lists, because a custom harness with one of these names would lose its icon.
            const MARKED_CLIENT_NAMES = ['PostHog AI', 'Slack']
            expect(Object.keys(HARNESS_BY_LABEL).sort()).toEqual(
                [...EXPECTED_HARNESS_LABELS, ...MARKED_CLIENT_NAMES].sort()
            )
        })

        it.each([
            'Claude Code',
            'OpenAI',
            'Cursor',
            'Linear',
            'CodeRabbit',
            'Notion',
            'Replit',
            'Windsurf',
            'opencode',
            'Lovable',
            'Manus',
            'LibreChat',
            'Pi',
            'Kimchi',
            'Antigravity',
            'Anthropic API',
            'Kiro',
            'PostHog CLI',
            'Poke',
            'Desktop Commander',
        ])('resolves a brand mark for the %s category', (category) => {
            expect(harnessMark(category)).not.toEqual('Other harnesses')
        })

        it.each([
            ['Other', 'Other harnesses'],
            ['Unidentified client', 'Unidentified client'],
            ['A harness with no mark yet', 'Other harnesses'],
        ])('falls back to a generic mark for %s', (category, expected) => {
            expect(harnessMark(category)).toEqual(expected)
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

        it('spans the supplied bucket keys and zero-fills days without calls', () => {
            const rows: ToolDailyRow[] = [{ day: '2024-01-02', tool: 'a', calls: 5 }]
            const bucketKeys = ['2024-01-01', '2024-01-02', '2024-01-03']
            expect(buildToolDailySeries(rows, bucketKeys)).toEqual({
                labels: bucketKeys,
                tools: [{ tool: 'a', data: [0, 5, 0] }],
            })
        })

        it('returns empty tools with the supplied labels when there are no rows', () => {
            expect(buildToolDailySeries([], ['2024-01-01'])).toEqual({ labels: ['2024-01-01'], tools: [] })
        })
    })

    describe('buildDailyActivity', () => {
        it('projects rows onto the bucket keys, defaulting missing buckets to zero', () => {
            const rows: ActivityRow[] = [
                { day: '2024-01-01 00:00:00', successes: 10, errors: 2 },
                { day: '2024-01-03 00:00:00', successes: 4, errors: 1 },
            ]
            const bucketKeys = ['2024-01-01 00:00:00', '2024-01-02 00:00:00', '2024-01-03 00:00:00']
            expect(buildDailyActivity(rows, bucketKeys)).toEqual({
                labels: bucketKeys,
                successes: [10, 0, 4],
                errors: [2, 0, 1],
            })
        })

        it('returns all-zero series when there are no rows', () => {
            const bucketKeys = ['2024-01-01 00:00:00', '2024-01-02 00:00:00', '2024-01-03 00:00:00']
            expect(buildDailyActivity([], bucketKeys)).toEqual({
                labels: bucketKeys,
                successes: [0, 0, 0],
                errors: [0, 0, 0],
            })
        })

        // The in-progress-tail dash applies `fromIndex = successes.length - 1` to line up with the
        // last bucket key, so the series must stay exactly bucketKeys-length — including when rows
        // fall outside the window. If this drifts, the dashed segment lands on the wrong point.
        it('keeps series length equal to bucketKeys, ignoring rows outside the window', () => {
            const bucketKeys = ['2024-01-01 00:00:00', '2024-01-02 00:00:00', '2024-01-03 00:00:00']
            const rows: ActivityRow[] = [
                { day: '2024-01-02 00:00:00', successes: 5, errors: 1 },
                { day: '2023-12-31 00:00:00', successes: 9, errors: 9 }, // outside bucketKeys — must be dropped
            ]
            const result = buildDailyActivity(rows, bucketKeys)
            expect(result.labels).toHaveLength(bucketKeys.length)
            expect(result.successes).toHaveLength(bucketKeys.length)
            expect(result.errors).toHaveLength(bucketKeys.length)
            expect(result.successes).toEqual([0, 5, 0])
        })
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
                sparklineLabels: ['2024-01-08', '2024-01-09'],
                goodDirection: 'up',
            })
            expect(kpis.toolCalls).toMatchObject({
                value: 300,
                previousValue: 50,
                deltaPct: 500,
                sparkline: [100, 200],
            })
            expect(kpis.p95LatencyMs).toMatchObject({ sparkline: [200, 300], goodDirection: 'down' })
            expect(kpis.errorRatePct).toMatchObject({
                value: (20 / 300) * 100,
                previousValue: 10,
                goodDirection: 'down',
            })
        })

        it('returns null deltas when there is no prior-period data', () => {
            const rows: BucketRow[] = [{ bucket: '2024-01-08', sessions: 10, tool_calls: 100, errors: 0, p95: 200 }]
            expect(buildKPIs(rows, '2024-01-08').sessions.deltaPct).toBeNull()
        })
    })

    describe('rankToolsByErrorRate', () => {
        const tool = (name: string, total_calls: number, error_rate_pct: number): ToolRow => ({
            tool: name,
            total_calls,
            errors: Math.round((total_calls * error_rate_pct) / 100),
            error_rate_pct,
            p95_duration_ms: 0,
        })

        it.each([
            ['skips a tool with too few calls to rank', [tool('one-call', 1, 100), tool('busy', 500, 4)], ['busy']],
            ['ranks qualifying tools by error rate', [tool('a', 20, 5), tool('b', 40, 10)], ['b', 'a']],
            ['returns nothing when no tool qualifies', [tool('a', 19, 50)], []],
        ])('%s', (_name, rows, expected) => {
            expect(rankToolsByErrorRate(rows).map((r) => r.tool)).toEqual(expected)
        })
    })

    describe('pickNotableSessions', () => {
        it('returns nothing for an empty set', () => {
            expect(pickNotableSessions([])).toEqual([])
        })

        it('picks one session per rule', () => {
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
            // A is the busiest, but it is already listed under worst_error_rate, so no high_activity row.
            expect(pickNotableSessions(rows).map((p) => ({ id: p.session.session_id, rule: p.rule }))).toEqual([
                { id: 'A', rule: 'worst_error_rate' },
                { id: 'B', rule: 'all_fail' },
                { id: 'C', rule: 'most_exploratory' },
                { id: 'D', rule: 'exemplar' },
            ])
        })

        it('lists a session that satisfies two rules once, under the first that matched', () => {
            const rows: SessionRow[] = [
                session({ session_id: 'both', tool_calls: 50, distinct_tools: 8, duration_seconds: 100 }),
                session({ session_id: 'filler-a', tool_calls: 2, distinct_tools: 1 }),
                session({ session_id: 'filler-b', tool_calls: 2, distinct_tools: 1 }),
            ]
            // 'both' is the most exploratory session and the volume outlier. Two rows would mean a
            // duplicate session_id, which is the table's React key.
            expect(pickNotableSessions(rows).map((p) => ({ id: p.session.session_id, rule: p.rule }))).toEqual([
                { id: 'both', rule: 'most_exploratory' },
            ])
        })

        it('returns nothing when every session is small, rather than reaching for a filler row', () => {
            const rows: SessionRow[] = [
                session({ session_id: 'errored', tool_calls: 2, errors: 1, error_rate_pct: 50, distinct_tools: 2 }),
                session({ session_id: 'clean', tool_calls: 2, distinct_tools: 2 }),
            ]
            expect(pickNotableSessions(rows)).toEqual([])
        })

        it('flags a genuine volume outlier and leaves unremarkable sessions out entirely', () => {
            const rows: SessionRow[] = [
                session({ session_id: 'firehose', tool_calls: 40, distinct_tools: 2, duration_seconds: 100 }),
                session({ session_id: 'explorer', tool_calls: 4, distinct_tools: 6, duration_seconds: 10 }),
                session({ session_id: 'single-a', tool_calls: 1, distinct_tools: 1 }),
                session({ session_id: 'single-b', tool_calls: 1, distinct_tools: 1 }),
            ]
            expect(pickNotableSessions(rows).map((p) => ({ id: p.session.session_id, rule: p.rule }))).toEqual([
                { id: 'explorer', rule: 'most_exploratory' },
                { id: 'firehose', rule: 'high_activity' },
            ])
        })
    })

    describe('kpiIncompleteTail', () => {
        beforeEach(() => {
            jest.clearAllMocks()
            initKeaTests()
            jest.spyOn(mockApi, 'query').mockResolvedValue({ results: [] })
        })

        // Reads the sparkline's own labels rather than the zero-filled axis: on a day with no calls
        // yet the KPI series stops at yesterday, which is settled, so dashing its last point would
        // mark a complete bucket as in progress.
        it('tracks the KPI sparkline labels, not the chart axis', async () => {
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const bucket = (daysAgo: number): string =>
                dayjs().tz(logic.values.timezone).subtract(daysAgo, 'day').startOf('day').format(BUCKET_FORMAT)
            const row = (daysAgo: number): BucketRow => ({
                bucket: bucket(daysAgo),
                sessions: 3,
                tool_calls: 30,
                errors: 1,
                p95: 100,
            })

            logic.actions.loadKPIsSuccess(buildKPIs([row(1), row(0)], bucket(1)))
            expect(logic.values.kpiIncompleteTail).toBe(true)

            logic.actions.loadKPIsSuccess(buildKPIs([row(3), row(2)], bucket(3)))
            expect(logic.values.kpiIncompleteTail).toBe(false)
        })
    })

    describe('model visibility', () => {
        beforeEach(() => {
            jest.clearAllMocks()
            initKeaTests()
            jest.spyOn(mockApi, 'query').mockResolvedValue({ results: [] } as any)
        })

        it.each([
            { rows: [], visible: false },
            { rows: [{ model: 'Unknown', total_calls: 12 }], visible: true },
            { rows: [{ model: 'gpt-5.6-sol', total_calls: 1 }], visible: true },
            { rows: [{ model: 'claude-sonnet-5', total_calls: 0 }], visible: false },
        ])('shows model coverage when calls exist: $rows', async ({ rows, visible }) => {
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.loadModelRowsSuccess(rows)
            expect(logic.values.hasModelData).toBe(visible)
        })
    })

    describe('protocol version visibility', () => {
        beforeEach(() => {
            jest.clearAllMocks()
            initKeaTests()
            jest.spyOn(mockApi, 'query').mockResolvedValue({ results: [] } as any)
        })

        it.each([
            { rows: [], visible: false },
            { rows: [{ protocol_version: 'Unknown', is_current: false, total_calls: 12 }], visible: true },
            { rows: [{ protocol_version: '2026-07-28', is_current: true, total_calls: 1 }], visible: true },
        ])('shows protocol version coverage when any call exists: $rows', async ({ rows, visible }) => {
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.loadProtocolVersionRowsSuccess(rows)
            expect(logic.values.hasProtocolVersionData).toBe(visible)
        })
    })

    describe('filter wiring', () => {
        beforeEach(() => {
            jest.clearAllMocks()
            initKeaTests()
            mockSections()
        })

        it('maps the period totals columns to the users and p95 metrics', async () => {
            mockSections((section) => (section === MCPDashboardSection.PeriodTotals ? [[42, 30, 900, 600]] : []))
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.periodTotals.users).toMatchObject({
                value: 42,
                previousValue: 30,
                deltaPct: 40,
                goodDirection: 'up',
            })
            expect(logic.values.headlineKpis.p95LatencyMs).toMatchObject({
                value: 900,
                previousValue: 600,
                deltaPct: 50,
                goodDirection: 'down',
            })
        })

        // Each card reads its own flag, so a reducer that marks the wrong loader puts the error on
        // the wrong card, and one that never clears leaves a card stuck after a successful retry.
        it.each([
            [MCPDashboardSection.Kpis, 'loadKPIs'],
            [MCPDashboardSection.PeriodTotals, 'loadPeriodTotals'],
            [MCPDashboardSection.ToolRows, 'loadToolRows'],
            [MCPDashboardSection.SessionRows, 'loadSessionRows'],
            [MCPDashboardSection.HarnessRows, 'loadHarnessRows'],
            [MCPDashboardSection.ModelRows, 'loadModelRows'],
            [MCPDashboardSection.ProtocolVersionRows, 'loadProtocolVersionRows'],
            [MCPDashboardSection.ActivityRows, 'loadActivityRows'],
            [MCPDashboardSection.ToolDailyRows, 'loadToolDailyRows'],
        ] as const)('flags only %s when its section fails, and clears it on retry', async (section, retry) => {
            mockSections((requested) => (requested === section ? new Error('Query timed out') : []))
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(Object.entries(logic.values.failedLoads).filter(([, failed]) => failed)).toEqual([[section, true]])
            expect(logic.values.feedbackLoadFailed).toBe(true)

            mockSections()
            await expectLogic(logic, () => {
                logic.actions[retry]()
            }).toFinishAllListeners()

            expect(logic.values.failedLoads[section]).toBe(false)
            expect(logic.values.feedbackLoadFailed).toBe(false)
        })

        it('ignores a failure from a request that a newer load already replaced', async () => {
            let rejectFirst: (error: unknown) => void = () => {}
            let periodTotalsCalls = 0
            mockApi.query.mockImplementation((node: any) => {
                const [section] = (node as MCPDashboardQuery).sections
                if (section === MCPDashboardSection.PeriodTotals && ++periodTotalsCalls === 1) {
                    return new Promise((_, reject) => (rejectFirst = reject)) as any
                }
                return Promise.resolve({ results: { [section]: { results: [] } } }) as any
            })
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic, () => {
                logic.actions.setDateFilter('-30d', null)
            }).toDispatchActions(['loadPeriodTotalsSuccess'])

            rejectFirst({ status: 504, detail: 'Query timed out' })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.failedLoads.periodTotals).toBeFalsy()
        })

        it('reloads every tile when the date filter changes', async () => {
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const callsBefore = mockApi.query.mock.calls.length

            await expectLogic(logic, () => {
                logic.actions.setDateFilter('-30d', null)
            }).toFinishAllListeners()

            const reloads = queriesSince(callsBefore)
            expect(reloads.flatMap((query) => query.sections).sort()).toEqual(
                [
                    MCPDashboardSection.Kpis,
                    MCPDashboardSection.PeriodTotals,
                    MCPDashboardSection.ToolRows,
                    MCPDashboardSection.SessionRows,
                    MCPDashboardSection.HarnessRows,
                    MCPDashboardSection.ModelRows,
                    MCPDashboardSection.ProtocolVersionRows,
                    MCPDashboardSection.ActivityRows,
                    MCPDashboardSection.ToolDailyRows,
                ].sort()
            )
            expect(reloads.every((query) => query.dateRange.date_from === '-30d')).toBe(true)
            // The KPI and users tiles compare against an absolute window one period earlier.
            expect(reloads.every((query) => dayjs(query.comparison.dateFrom).isValid())).toBe(true)
        })

        // The server caches a query by its exact filters, so a window that moves with the clock makes
        // every load recompute the two slowest tiles.
        it.each(['-7d', '-24h', '-90d'])('keeps the comparison window stable between %s loads', async (dateFrom) => {
            jest.useFakeTimers({ now: new Date('2026-11-06T14:23:41.517Z'), advanceTimers: true })
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            const windowOf = (callIndex: number): MCPDashboardQuery['comparison'][] =>
                queriesSince(callIndex)
                    .filter((query) =>
                        [MCPDashboardSection.Kpis, MCPDashboardSection.PeriodTotals].includes(query.sections[0])
                    )
                    .map((query) => query.comparison)

            await expectLogic(logic, () => logic.actions.setDateFilter(dateFrom, null)).toFinishAllListeners()
            const first = windowOf(mockApi.query.mock.calls.length - 9)
            jest.setSystemTime(new Date('2026-11-06T14:23:58.004Z'))
            const callsBefore = mockApi.query.mock.calls.length
            await expectLogic(logic, () => logic.actions.reloadAll()).toFinishAllListeners()
            jest.useRealTimers()

            expect(first).toHaveLength(2)
            expect(windowOf(callsBefore)).toEqual(first)
        })

        // A previous period longer than the selected one makes flat traffic read as a drop. Sub-day ranges
        // split on the start of the selected period's first bucket, which skews them by up to two intervals,
        // so only whole-day ranges are pinned.
        it.each(['-7d', '-90d'])('compares %s against a previous period of the same length', async (dateFrom) => {
            jest.useFakeTimers({ now: new Date('2026-11-06T00:59:59.900Z'), advanceTimers: true })
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            const callsBefore = mockApi.query.mock.calls.length
            await expectLogic(logic, () => logic.actions.setDateFilter(dateFrom, null)).toFinishAllListeners()
            const now = dayjs()
            jest.useRealTimers()

            const totals = queriesSince(callsBefore).find(
                (query) => query.sections[0] === MCPDashboardSection.PeriodTotals
            )!
            const selectedStart = dayjs.tz(totals.comparison.currentStartBucket, logic.values.timezone)
            const previousMs = selectedStart.diff(dayjs(totals.comparison.dateFrom))
            expect(Math.abs(previousMs - now.diff(selectedStart))).toBeLessThan(60_000)
        })

        // Rounding a window shorter than one bucket would reach into the selected period's first bucket and
        // count events from before the selected start as current.
        it('leaves a window shorter than one bucket where it starts', async () => {
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            const callsBefore = mockApi.query.mock.calls.length

            await expectLogic(logic, () =>
                logic.actions.setDateFilter('2026-11-06T14:00:00Z', '2026-11-06T14:30:00Z')
            ).toFinishAllListeners()

            const windows = queriesSince(callsBefore)
                .filter((query) =>
                    [MCPDashboardSection.Kpis, MCPDashboardSection.PeriodTotals].includes(query.sections[0])
                )
                .map((query) => dayjs(query.comparison.dateFrom).toISOString())
            expect(windows).toEqual(['2026-11-06T13:30:00.000Z', '2026-11-06T13:30:00.000Z'])
        })

        it.each([[false], [true]])('passes filterTestAccounts=%s to every tile', async (enabled) => {
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            // enabled=false is the default mount state; enabled=true reloads after toggling.
            const callsBefore = enabled ? mockApi.query.mock.calls.length : 0

            if (enabled) {
                await expectLogic(logic, () => {
                    logic.actions.setFilterTestAccounts(true)
                }).toFinishAllListeners()
            }

            const reloads = queriesSince(callsBefore)
            expect(reloads.length).toBe(9)
            expect(reloads.every((query) => query.filterTestAccounts === enabled)).toBe(true)
        })

        it('defaults the filter from the team test_account_filters_default_checked setting', async () => {
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, test_account_filters_default_checked: true })
            mockSections()
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            // No explicit toggle, yet every tile filters internal users because the team default is on.
            const reloads = queriesSince(0)
            expect(reloads.length).toBeGreaterThanOrEqual(9)
            expect(reloads.every((query) => query.filterTestAccounts === true)).toBe(true)
        })

        const EVENT_FILTER: AnyPropertyFilter = {
            key: '$mcp_tool_name',
            value: ['create_insight'],
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        }

        it.each([
            { label: 'shared filters', params: {}, dateFrom: '-7d' },
            { label: 'date and shared filters', params: { date_from: '-30d' }, dateFrom: '-30d' },
        ])('reloads tiles once when the URL changes the $label', async ({ params, dateFrom }) => {
            router.actions.push(urls.mcpAnalyticsDashboard())
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const callsBefore = mockApi.query.mock.calls.length

            await expectLogic(logic, () => {
                router.actions.push(urls.mcpAnalyticsDashboard(), {
                    ...params,
                    properties: [EVENT_FILTER],
                    filter_test_accounts: true,
                })
            }).toFinishAllListeners()

            const reloads = queriesSince(callsBefore)
            expect(reloads).toHaveLength(9)
            expect(reloads).toEqual(
                reloads.map(() =>
                    expect.objectContaining({
                        dateRange: { date_from: dateFrom, date_to: null },
                        properties: [EVENT_FILTER],
                        filterTestAccounts: true,
                    })
                )
            )
        })

        it('opens a tool report on the dashboard window with the shared filters', async () => {
            router.actions.push(urls.mcpAnalyticsDashboard(), {
                properties: [EVENT_FILTER],
                filter_test_accounts: true,
            })
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.openToolReport('search docs')

            const { pathname, searchParams } = router.values.currentLocation
            expect(pathname.endsWith(urls.mcpAnalyticsTool('search docs'))).toBe(true)
            expect(searchParams).toEqual({
                date_from: '-7d',
                properties: [EVENT_FILTER],
                filter_test_accounts: true,
            })
        })

        // Feature-flag filters arrive as ordinary $feature/<key> event-property filters.
        const FLAG_FILTER: AnyPropertyFilter = {
            key: '$feature/mcp-new-thing',
            value: ['test'],
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        }

        it.each([
            ['event property', EVENT_FILTER],
            ['feature flag', FLAG_FILTER],
        ])('passes %s filters to every tile', async (_label, filter) => {
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const callsBefore = mockApi.query.mock.calls.length

            await expectLogic(logic, () => {
                logic.actions.setPropertyFilters([filter])
            }).toFinishAllListeners()

            const reloads = queriesSince(callsBefore)
            expect(reloads.length).toBe(9)
            expect(reloads.every((query) => JSON.stringify(query.properties) === JSON.stringify([filter]))).toBe(true)
        })

        it.each(['date', 'property', 'test accounts'])(
            'offers feedback after a %s interaction and a successful nonempty refresh',
            async (filter) => {
                const populated = (section: MCPDashboardSection): unknown[] =>
                    section === MCPDashboardSection.Kpis ? [[dayjs().format('YYYY-MM-DD'), 2, 10, 0, 100]] : []
                mockSections(populated)
                router.actions.push(urls.mcpAnalyticsDashboard(), { date_from: '-14d' })
                const logic = mcpDashboardOverviewLogic()
                logic.mount()
                await expectLogic(logic).toFinishAllListeners()
                expect(logic.values.kpis.toolCalls.value).toBe(10)
                expect(logic.values.canShowFeedback).toBe(false)

                if (filter === 'date') {
                    logic.actions.setDateFilter('-30d', null)
                    logic.actions.markFilterInteraction()
                } else if (filter === 'property') {
                    logic.actions.setPropertyFilters([EVENT_FILTER])
                } else {
                    logic.actions.setFilterTestAccounts(true)
                }
                expect(logic.values.canShowFeedback).toBe(false)
                await expectLogic(logic).toFinishAllListeners()
                expect(logic.values.canShowFeedback).toBe(true)
                const previousContext = logic.values.feedbackContextKey

                mockSections((section) =>
                    section === MCPDashboardSection.HarnessRows
                        ? new Error('Example query failure')
                        : populated(section)
                )
                await expectLogic(logic, () => logic.actions.setDateFilter('-7d', null)).toFinishAllListeners()
                expect(logic.values.feedbackContextKey).toBe(previousContext)
                expect(logic.values.canShowFeedback).toBe(false)

                mockSections()
                await expectLogic(logic, () => logic.actions.reloadAll()).toFinishAllListeners()
                expect(logic.values.canShowFeedback).toBe(false)

                mockSections(populated)
                await expectLogic(logic, () => logic.actions.reloadAll()).toFinishAllListeners()
                expect(logic.values.canShowFeedback).toBe(true)
            }
        )
    })
})
