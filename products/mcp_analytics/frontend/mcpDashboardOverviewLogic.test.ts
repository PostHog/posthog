import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { BUCKET_FORMAT } from 'lib/utils/timeBuckets'
import { urls } from 'scenes/urls'

import { MCPDashboardQuery, MCPDashboardSection } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { HARNESS_BY_LABEL, harnessMark } from './dashboard/harnessRegistry'
import { mcpLeaderboardHomeLogic } from './leaderboardHome/mcpLeaderboardHomeLogic'
import {
    type ActivityRow,
    type BucketRow,
    buildDailyActivity,
    buildKPIs,
    rankToolsByErrorRate,
    rankToolsByP95,
    buildToolDailySeries,
    type DashboardLayout,
    deltaPct,
    mcpDashboardOverviewLogic,
    pickNotableSessions,
    type SessionRow,
    type ToolRow,
    type ToolDailyRow,
} from './mcpDashboardOverviewLogic'

jest.mock('lib/api')
jest.mock('posthog-js')
jest.mock('./generated/api', () => ({
    mcpAnalyticsIntentClustersRetrieve: jest.fn().mockResolvedValue({ status: 'idle', clusters: [] }),
    mcpAnalyticsIntentClustersRecompute: jest.fn(),
}))

const mockApi = api as jest.Mocked<typeof api>

type Answer = unknown[] | Error

function failedRequest(status: number, message: string): Error {
    return Object.assign(new Error(message), { status })
}

function sectionResponse(sections: MCPDashboardSection[], respond: (section: MCPDashboardSection) => Answer): object {
    const answers = sections.map((section) => [section, respond(section)] as const)
    const failure = answers.find(([, answer]) => answer instanceof Error)?.[1]
    // The server computes a one-section query by itself, so the section's failure fails the request.
    if (sections.length === 1 && failure instanceof Error) {
        throw failedRequest(500, failure.message)
    }
    return {
        results: Object.fromEntries(
            answers.map(([section, answer]) => [
                section,
                answer instanceof Error ? { error: answer.message } : { results: answer },
            ])
        ),
    }
}

function mockSections(respond: (section: MCPDashboardSection) => Answer = () => []): void {
    mockApi.query.mockImplementation(async (node: any) =>
        sectionResponse((node as MCPDashboardQuery).sections, respond)
    )
}

interface PendingQueries {
    answer: (section: MCPDashboardSection, rows: unknown[]) => void
    answerAt: (index: number) => void
    answerAll: () => void
}

function deferQueries(): PendingQueries {
    const pending: { sections: MCPDashboardSection[]; resolve: (rows: unknown[]) => void }[] = []
    mockApi.query.mockImplementation(
        (node: any) =>
            new Promise((resolve) => {
                const { sections } = node as MCPDashboardQuery
                pending.push({ sections, resolve: (rows) => resolve(sectionResponse(sections, () => rows)) })
            })
    )
    return {
        answer: (section, rows) => pending.find((query) => query.sections.join() === section)?.resolve(rows),
        answerAt: (index) => pending[index].resolve([]),
        answerAll: () => pending.forEach((query) => query.resolve([])),
    }
}

function queriesSince(callIndex: number): MCPDashboardQuery[] {
    return mockApi.query.mock.calls.slice(callIndex).map((call) => call[0] as MCPDashboardQuery)
}

function useLayout(layout: DashboardLayout, batched = true): void {
    const flags: Record<string, boolean> = {
        [FEATURE_FLAGS.MCP_ANALYTICS_LEADERBOARD_HOME]: layout === 'leaderboard',
        [FEATURE_FLAGS.MCP_ANALYTICS_DASHBOARD_BATCH]: batched,
    }
    featureFlagLogic.actions.setFeatureFlags(
        Object.keys(flags).filter((flag) => flags[flag]),
        flags
    )
}

function timeToSeeDataEvents(): Record<string, any>[] {
    return (posthog.capture as jest.Mock).mock.calls
        .filter(([event]) => event === 'time to see data')
        .map(([, payload]) => payload)
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

    describe('ranking tools', () => {
        const tool = (name: string, total_calls: number, error_rate_pct: number, p95_duration_ms = 0): ToolRow => ({
            tool: name,
            total_calls,
            errors: Math.round((total_calls * error_rate_pct) / 100),
            error_rate_pct,
            p95_duration_ms,
        })

        it.each([
            ['skips a tool with too few calls to rank', [tool('one-call', 1, 100), tool('busy', 500, 4)], ['busy']],
            ['ranks qualifying tools by error rate', [tool('a', 20, 5), tool('b', 40, 10)], ['b', 'a']],
            ['returns nothing when no tool qualifies', [tool('a', 19, 50)], []],
        ])('by error rate %s', (_name, rows, expected) => {
            expect(rankToolsByErrorRate(rows).map((r) => r.tool)).toEqual(expected)
        })

        it.each([
            [
                'skips a tool with too few calls to rank',
                [tool('one-call', 1, 0, 90_000), tool('busy', 500, 0, 800)],
                ['busy'],
            ],
            ['ranks qualifying tools by p95', [tool('a', 20, 0, 300), tool('b', 40, 0, 2500)], ['b', 'a']],
            [
                'skips a tool whose calls carry no duration',
                [tool('untimed', 500, 0, 0), tool('timed', 30, 0, 50)],
                ['timed'],
            ],
        ])('by p95 %s', (_name, rows, expected) => {
            expect(rankToolsByP95(rows).map((r) => r.tool)).toEqual(expected)
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

    describe('loading the dashboard', () => {
        beforeEach(() => {
            jest.clearAllMocks()
            initKeaTests()
            useLayout('overview')
            mockSections()
        })

        async function mountDashboard(): Promise<ReturnType<typeof mcpDashboardOverviewLogic.build>> {
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            mcpLeaderboardHomeLogic.mount()
            await expectLogic(logic).toFinishAllListeners()
            return logic
        }

        // The leaderboard renders its own protocol and tool facets, so it must not pay for the
        // overview-only breakdowns. It keeps modelRows as the model chart's fallback.
        it.each([
            {
                layout: 'overview' as const,
                includes: [
                    MCPDashboardSection.Kpis,
                    MCPDashboardSection.PeriodTotals,
                    MCPDashboardSection.ToolDailyRows,
                ],
                excludes: [MCPDashboardSection.Reliability, MCPDashboardSection.Model],
            },
            {
                layout: 'leaderboard' as const,
                includes: [MCPDashboardSection.Kpis, MCPDashboardSection.ModelRows, MCPDashboardSection.Reliability],
                excludes: [MCPDashboardSection.ProtocolVersionRows, MCPDashboardSection.ToolDailyRows],
            },
        ])('loads the $layout layout in one request', async ({ layout, includes, excludes }) => {
            useLayout(layout)
            await mountDashboard()

            const queries = queriesSince(0)
            expect(queries).toHaveLength(1)
            expect(queries[0].sections).toEqual(expect.arrayContaining(includes))
            expect(queries[0].sections.filter((section) => excludes.includes(section))).toEqual([])
        })

        it.each([
            { layout: 'overview' as const, requests: 9 },
            { layout: 'leaderboard' as const, requests: 14 },
        ])('sends one request per section in the $layout baseline arm', async ({ layout, requests }) => {
            useLayout(layout, false)
            mockSections((section) => (section === MCPDashboardSection.PeriodTotals ? [[42, 30, 900, 600]] : []))
            const logic = await mountDashboard()

            const queries = queriesSince(0)
            expect(queries).toHaveLength(requests)
            expect(queries.every((query) => query.sections.length === 1)).toBe(true)
            expect(logic.values.periodTotals.users.value).toBe(42)
            expect(timeToSeeDataEvents().map((event) => event.status)).toEqual(['success'])
        })

        it('shows a section in the baseline arm while slower sections are still loading', async () => {
            useLayout('overview', false)
            const pending = deferQueries()
            const logic = mcpDashboardOverviewLogic()
            logic.mount()

            pending.answer(MCPDashboardSection.PeriodTotals, [[42, 30, 900, 600]])
            await expectLogic(logic).delay(0)

            expect(logic.values.periodTotals.users.value).toBe(42)
            expect(logic.values.loadingSections).not.toHaveProperty(MCPDashboardSection.PeriodTotals)
            expect(logic.values.loadingSections[MCPDashboardSection.Kpis]).toBe(true)
            expect(timeToSeeDataEvents()).toEqual([])

            pending.answerAll()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.dashboardLoading).toBe(false)
            expect(timeToSeeDataEvents().map((event) => event.status)).toEqual(['success'])
        })

        // A period with no calls compares zero with zero, so its tiles show a 0% change rather than none.
        it.each([
            { rows: [[42, 30, 900, 600]], users: [42, 30, 40], p95: [900, 600, 50] },
            { rows: [], users: [0, 0, 0], p95: [0, 0, 0] },
        ])('maps the period totals columns to the users and p95 metrics: $rows', async ({ rows, users, p95 }) => {
            mockSections((section) => (section === MCPDashboardSection.PeriodTotals ? rows : []))
            const logic = await mountDashboard()

            const [value, previousValue, delta] = users
            expect(logic.values.periodTotals.users).toMatchObject({
                value,
                previousValue,
                deltaPct: delta,
                goodDirection: 'up',
            })
            expect(logic.values.headlineKpis.p95LatencyMs).toMatchObject({
                value: p95[0],
                previousValue: p95[1],
                deltaPct: p95[2],
                goodDirection: 'down',
            })
        })

        it.each(
            [
                { failing: MCPDashboardSection.Kpis, toasts: false },
                { failing: MCPDashboardSection.PeriodTotals, toasts: false },
                { failing: MCPDashboardSection.ToolRows, toasts: false },
                { failing: MCPDashboardSection.SessionRows, toasts: false },
                { failing: MCPDashboardSection.HarnessRows, toasts: false },
                { failing: MCPDashboardSection.ModelRows, toasts: true },
                { failing: MCPDashboardSection.ProtocolVersionRows, toasts: true },
                { failing: MCPDashboardSection.ActivityRows, toasts: false },
                { failing: MCPDashboardSection.ToolDailyRows, toasts: false },
            ].flatMap((row) => [
                { ...row, batched: true, captured: 0 },
                { ...row, batched: false, captured: 1 },
            ])
        )(
            'flags and retries only the $failing card when its section fails (batched $batched)',
            async ({ failing, toasts, batched, captured }) => {
                useLayout('overview', batched)
                const toastError = jest.spyOn(lemonToast, 'error')
                const answers: Partial<Record<MCPDashboardSection, unknown[]>> = {
                    [MCPDashboardSection.PeriodTotals]: [[42, 30, 900, 600]],
                    [MCPDashboardSection.ToolRows]: [['search_docs', 4, 1, 25, 120]],
                }
                mockSections((section) => (section === failing ? new Error('Query failed') : (answers[section] ?? [])))
                const logic = await mountDashboard()

                expect(logic.values.failedLoads).toEqual({ [failing]: true })
                expect(logic.values.periodTotals.users.value).toBe(
                    failing === MCPDashboardSection.PeriodTotals ? 0 : 42
                )
                expect(logic.values.toolRows).toHaveLength(failing === MCPDashboardSection.ToolRows ? 0 : 1)
                expect(toastError).toHaveBeenCalledTimes(toasts ? 1 : 0)
                expect(posthog.captureException).toHaveBeenCalledTimes(captured)

                const callsBefore = mockApi.query.mock.calls.length
                const pending = deferQueries()
                logic.actions.loadSections([failing])
                expect(queriesSince(callsBefore).map((query) => query.sections)).toEqual([[failing]])
                expect(logic.values.loadingSections).toEqual({ [failing]: true })
                expect(logic.values.failedLoads).toEqual({})
                expect(logic.values.toolRows).toHaveLength(failing === MCPDashboardSection.ToolRows ? 0 : 1)

                pending.answerAll()
                await expectLogic(logic).toFinishAllListeners()
                expect(logic.values.dashboardLoading).toBe(false)
                expect(logic.values.failedLoads).toEqual({})
            }
        )

        it.each([
            { layout: 'overview' as const, batched: true, error: new Error('Failed to fetch'), failed: 9 },
            {
                layout: 'overview' as const,
                batched: true,
                error: { status: 403, detail: 'You do not have access.' },
                failed: 9,
            },
            { layout: 'overview' as const, batched: true, error: { status: 500, detail: 'Server error' }, failed: 9 },
            { layout: 'overview' as const, batched: false, error: new Error('Failed to fetch'), failed: 9 },
            {
                layout: 'overview' as const,
                batched: false,
                error: { status: 403, detail: 'You do not have access.' },
                failed: 9,
            },
            {
                layout: 'leaderboard' as const,
                batched: true,
                error: { status: 500, detail: 'Server error' },
                failed: 14,
            },
        ])(
            'clears the previous rows without a toast when the $layout request fails: batched $batched, $error',
            async ({ layout, batched, error, failed }) => {
                useLayout(layout, batched)
                const toastError = jest.spyOn(lemonToast, 'error')
                const answers: Partial<Record<MCPDashboardSection, unknown[]>> = {
                    [MCPDashboardSection.ToolRows]: [['search_docs', 4, 1, 25, 120]],
                    [MCPDashboardSection.Tool]: [['search_docs', 4, 1, 0]],
                }
                mockSections((section) => answers[section] ?? [])
                const logic = await mountDashboard()
                expect(logic.values.toolRows).toHaveLength(1)

                mockApi.query.mockRejectedValue(error)
                await expectLogic(logic, () => logic.actions.setDateFilter('-30d', null)).toFinishAllListeners()

                expect(logic.values.toolRows).toEqual([])
                expect(mcpLeaderboardHomeLogic.values.facets.tool).toEqual([])
                expect(Object.keys(logic.values.failedLoads)).toHaveLength(failed)
                expect(toastError).not.toHaveBeenCalled()
                expect(timeToSeeDataEvents().map((event) => event.status)).toEqual(['success', 'failure'])
            }
        )

        it.each(
            [
                { failing: MCPDashboardSection.Model, failedFacets: ['model'], reliabilityFailed: false },
                {
                    failing: MCPDashboardSection.ProtocolVersion,
                    failedFacets: ['protocolVersion'],
                    reliabilityFailed: false,
                },
                { failing: MCPDashboardSection.Tool, failedFacets: ['tool'], reliabilityFailed: false },
                { failing: MCPDashboardSection.ErrorType, failedFacets: ['errorType'], reliabilityFailed: false },
                { failing: MCPDashboardSection.LabUsers, failedFacets: ['labUsers'], reliabilityFailed: false },
                {
                    failing: MCPDashboardSection.NamedModelUsers,
                    failedFacets: ['namedModelUsers'],
                    reliabilityFailed: false,
                },
                { failing: MCPDashboardSection.Reliability, failedFacets: [], reliabilityFailed: true },
            ].flatMap((row) => [
                { ...row, batched: true },
                { ...row, batched: false },
            ])
        )('flags only the leaderboard $failing card when its section fails (batched $batched)', async (row) => {
            useLayout('leaderboard', row.batched)
            const toastError = jest.spyOn(lemonToast, 'error')
            const answers: Partial<Record<MCPDashboardSection, unknown[]>> = {
                [MCPDashboardSection.Model]: [['2026-11-01', 'claude-sonnet-5', 4]],
                [MCPDashboardSection.ToolRows]: [['search_docs', 4, 1, 25, 120]],
            }
            mockSections((section) => (section === row.failing ? new Error('Query failed') : (answers[section] ?? [])))
            const logic = await mountDashboard()

            const { facets, reliabilityFailed } = mcpLeaderboardHomeLogic.values
            expect(facets.failedFacets).toEqual(row.failedFacets)
            expect(reliabilityFailed).toBe(row.reliabilityFailed)
            expect(facets.model).toHaveLength(row.failing === MCPDashboardSection.Model ? 0 : 1)
            expect(logic.values.toolRows.map((toolRow) => toolRow.tool)).toEqual(['search_docs'])
            expect(toastError).not.toHaveBeenCalled()
        })

        it.each([
            { batched: true, requests: 1 },
            { batched: false, requests: 9 },
        ])(
            'ignores the failure of a request a newer load replaced (batched $batched)',
            async ({ batched, requests }) => {
                useLayout('overview', batched)
                const rejects: ((error: Error) => void)[] = []
                mockApi.query.mockImplementation(() => new Promise((_, reject) => rejects.push(reject)))
                const logic = mcpDashboardOverviewLogic()
                logic.mount()
                logic.actions.reloadAll()

                rejects.slice(0, requests).forEach((reject) => reject(new Error('Gateway timeout')))
                await expectLogic(logic).delay(0)

                expect(logic.values.dashboardLoading).toBe(true)
                expect(logic.values.failedLoads).toEqual({})
                expect(posthog.captureException).not.toHaveBeenCalled()
                expect(timeToSeeDataEvents()).toEqual([])
            }
        )

        it('reloads with the leaderboard sections when its flag resolves after mount', async () => {
            await mountDashboard()

            await expectLogic(mcpDashboardOverviewLogic, () => useLayout('leaderboard')).toFinishAllListeners()

            const queries = queriesSince(1)
            expect(queries).toHaveLength(1)
            expect(queries[0].sections).toContain(MCPDashboardSection.Reliability)
        })

        it('stops counting the sections of a replaced layout as loading', async () => {
            const pending = deferQueries()
            const logic = mcpDashboardOverviewLogic()
            logic.mount()

            useLayout('leaderboard')
            pending.answerAt(1)
            await expectLogic(logic).delay(0)

            expect(logic.values.loadingSections).toEqual({})
            expect(logic.values.dashboardLoading).toBe(false)
        })

        it.each([{ searchParams: {} }, { searchParams: { date_from: '-30d' } }])(
            'reports a load the dashboard leaves unfinished as cancelled: $searchParams',
            async ({ searchParams }) => {
                router.actions.push(urls.mcpAnalyticsDashboard(), searchParams)
                deferQueries()
                const logic = mcpDashboardOverviewLogic()
                logic.mount()
                await expectLogic(logic).delay(0)

                logic.unmount()

                expect(timeToSeeDataEvents()).toEqual([
                    expect.objectContaining({ status: 'cancelled', cancel_reason: 'navigated_away' }),
                ])
            }
        )

        // The time to see data event carries the flag's value when it is sent, so the load it measures must
        // be the batched one, not the baseline load the late flag replaced.
        it('reloads in one request when the batch flag resolves after mount', async () => {
            useLayout('overview', false)
            const pending = deferQueries()
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            expect(queriesSince(0)).toHaveLength(9)

            useLayout('overview', true)
            const reload = queriesSince(9)
            expect(reload).toHaveLength(1)
            expect(reload[0].sections).toHaveLength(9)

            pending.answerAt(9)
            await expectLogic(logic).delay(0)
            expect(timeToSeeDataEvents().map((event) => event.status)).toEqual(['success'])

            pending.answerAll()
            await expectLogic(logic).toFinishAllListeners()
            expect(timeToSeeDataEvents()).toHaveLength(1)
        })

        it.each([
            { batched: true, failing: null, status: 'success' },
            { batched: true, failing: MCPDashboardSection.HarnessRows, status: 'failure' },
            { batched: false, failing: null, status: 'success' },
            { batched: false, failing: MCPDashboardSection.HarnessRows, status: 'failure' },
        ])('reports time to see data as $status once per load (batched $batched)', async (row) => {
            useLayout('overview', row.batched)
            mockSections((section) => (section === row.failing ? new Error('Query failed') : []))
            await mountDashboard()

            expect(timeToSeeDataEvents()).toEqual([
                expect.objectContaining({
                    context: 'mcp-analytics-dashboard',
                    action: 'initial_load',
                    status: row.status,
                    insights_fetched: 1,
                }),
            ])
        })

        // Reads the sparkline's own labels rather than the zero-filled axis: on a day with no calls
        // yet the KPI series stops at yesterday, which is settled, so dashing its last point would
        // mark a complete bucket as in progress.
        it('tracks the KPI sparkline labels, not the chart axis', async () => {
            const logic = await mountDashboard()
            const bucket = (daysAgo: number): string =>
                dayjs().tz(logic.values.timezone).subtract(daysAgo, 'day').startOf('day').format(BUCKET_FORMAT)
            const row = (daysAgo: number): unknown[] => [bucket(daysAgo), 3, 30, 1, 100]
            const load = (rows: unknown[][], currentStartBucket: string): void =>
                logic.actions.sectionsLoaded({ [MCPDashboardSection.Kpis]: { results: rows, currentStartBucket } })

            load([row(1), row(0)], bucket(1))
            expect(logic.values.kpiIncompleteTail).toBe(true)

            load([row(3), row(2)], bucket(3))
            expect(logic.values.kpiIncompleteTail).toBe(false)
        })

        it.each([
            { section: MCPDashboardSection.ModelRows, rows: [], visible: false },
            { section: MCPDashboardSection.ModelRows, rows: [{ model: 'Unknown', total_calls: 12 }], visible: true },
            {
                section: MCPDashboardSection.ModelRows,
                rows: [{ model: 'claude-sonnet-5', total_calls: 0 }],
                visible: false,
            },
            { section: MCPDashboardSection.ProtocolVersionRows, rows: [], visible: false },
            {
                section: MCPDashboardSection.ProtocolVersionRows,
                rows: [{ protocol_version: 'Unknown', is_current: false, total_calls: 12 }],
                visible: true,
            },
        ])('shows $section coverage only when calls exist: $rows', async ({ section, rows, visible }) => {
            mockSections((requested) => (requested === section ? rows : []))
            const logic = await mountDashboard()

            const shown =
                section === MCPDashboardSection.ModelRows
                    ? logic.values.hasModelData
                    : logic.values.hasProtocolVersionData
            expect(shown).toBe(visible)
        })
    })

    describe('filter wiring', () => {
        beforeEach(() => {
            jest.clearAllMocks()
            initKeaTests()
            useLayout('overview')
            mockSections()
        })

        it('reloads every section when the date filter changes', async () => {
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const callsBefore = mockApi.query.mock.calls.length

            await expectLogic(logic, () => {
                logic.actions.setDateFilter('-30d', null)
            }).toFinishAllListeners()

            const queries = queriesSince(callsBefore)
            expect(queries).toHaveLength(1)
            expect(queries[0].sections).toHaveLength(9)
            expect(queries[0].dateRange).toEqual({ date_from: '-30d', date_to: null })
            // The KPI tiles compare against an absolute window one period earlier.
            expect(dayjs(queries[0].comparison.dateFrom).isValid()).toBe(true)
        })

        // The server caches a query by its exact filters, so a window that moves with the clock makes
        // every load recompute the two slowest tiles.
        it.each(['-7d', '-24h', '-90d'])('keeps the comparison window stable between %s loads', async (dateFrom) => {
            jest.useFakeTimers({ now: new Date('2026-11-06T14:23:41.517Z'), advanceTimers: true })
            const logic = mcpDashboardOverviewLogic()
            logic.mount()

            await expectLogic(logic, () => logic.actions.setDateFilter(dateFrom, null)).toFinishAllListeners()
            const first = queriesSince(mockApi.query.mock.calls.length - 1)[0].comparison
            jest.setSystemTime(new Date('2026-11-06T14:23:58.004Z'))
            const callsBefore = mockApi.query.mock.calls.length
            await expectLogic(logic, () => logic.actions.reloadAll()).toFinishAllListeners()
            jest.useRealTimers()

            expect(queriesSince(callsBefore).map((query) => query.comparison)).toEqual([first])
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

            const { comparison } = queriesSince(callsBefore)[0]
            const selectedStart = dayjs.tz(comparison.currentStartBucket, logic.values.timezone)
            const previousMs = selectedStart.diff(dayjs(comparison.dateFrom))
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

            const windows = queriesSince(callsBefore).map((query) => dayjs(query.comparison.dateFrom).toISOString())
            expect(windows).toEqual(['2026-11-06T13:30:00.000Z'])
        })

        it.each([[false], [true]])('passes filterTestAccounts=%s to the dashboard query', async (enabled) => {
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

            expect(queriesSince(callsBefore).map((query) => query.filterTestAccounts)).toEqual([enabled])
        })

        it('defaults the filter from the team test_account_filters_default_checked setting', async () => {
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, test_account_filters_default_checked: true })
            mockSections()
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const queries = queriesSince(0)
            expect(queries.length).toBeGreaterThanOrEqual(1)
            expect(queries.every((query) => query.filterTestAccounts === true)).toBe(true)
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
        ])('reloads once when the URL changes the $label', async ({ params, dateFrom }) => {
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

            expect(queriesSince(callsBefore)).toEqual([
                expect.objectContaining({
                    dateRange: { date_from: dateFrom, date_to: null },
                    properties: [EVENT_FILTER],
                    filterTestAccounts: true,
                }),
            ])
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
        ])('passes %s filters to the dashboard query', async (_label, filter) => {
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const callsBefore = mockApi.query.mock.calls.length

            await expectLogic(logic, () => {
                logic.actions.setPropertyFilters([filter])
            }).toFinishAllListeners()

            expect(queriesSince(callsBefore).map((query) => query.properties)).toEqual([[filter]])
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
