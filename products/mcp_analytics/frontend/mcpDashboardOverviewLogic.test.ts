import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { HARNESS_BY_LABEL, harnessLogo } from './dashboard/harnessRegistry'
import {
    type ActivityRow,
    type BucketRow,
    buildBucketKeys,
    buildDailyActivity,
    buildKPIs,
    buildKpiWindow,
    buildToolDailySeries,
    deltaPct,
    lastBucketIsInProgress,
    mcpDashboardOverviewLogic,
    normalizeBucket,
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
    describe('harnessLogo', () => {
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
            'Antigravity',
            'Poke',
            'opencode',
            'Kiro',
            'Desktop Commander',
        ]

        it.each(EXPECTED_HARNESS_LABELS)('HARNESS_BY_LABEL has an entry for backend label %s', (label) => {
            expect(Object.prototype.hasOwnProperty.call(HARNESS_BY_LABEL, label)).toBe(true)
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
            'Antigravity',
        ])('resolves a logo for the %s category', (category) => {
            expect(harnessLogo(category)?.src).toBeTruthy()
        })

        it.each(['Anthropic API', 'Poke', 'Kiro', 'Desktop Commander', 'Other'])(
            'has no logo for the logo-less %s category',
            (category) => {
                expect(harnessLogo(category)).toBeUndefined()
            }
        )
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

    describe('buildBucketKeys', () => {
        it('emits one key per day across the resolved window, including empty trailing days', () => {
            jest.useFakeTimers().setSystemTime(new Date('2026-06-18T12:00:00Z'))
            try {
                expect(buildBucketKeys({ dateFrom: '-7d', dateTo: null }, 'UTC', 'day')).toEqual([
                    '2026-06-11 00:00:00',
                    '2026-06-12 00:00:00',
                    '2026-06-13 00:00:00',
                    '2026-06-14 00:00:00',
                    '2026-06-15 00:00:00',
                    '2026-06-16 00:00:00',
                    '2026-06-17 00:00:00',
                    '2026-06-18 00:00:00',
                ])
            } finally {
                jest.useRealTimers()
            }
        })

        it('truncates weekly buckets to ISO Monday starts (matching ClickHouse dateTrunc)', () => {
            // 2026-06-01 is a Monday; every key should land on a Monday.
            const keys = buildBucketKeys({ dateFrom: '2026-06-01', dateTo: '2026-06-21' }, 'UTC', 'week')
            expect(keys).toEqual(['2026-06-01 00:00:00', '2026-06-08 00:00:00', '2026-06-15 00:00:00'])
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

    describe('lastBucketIsInProgress', () => {
        const tz = 'UTC'
        const keys = ['2026-06-27 00:00:00', '2026-06-28 00:00:00', '2026-06-29 00:00:00']

        it('flags the tail when the last bucket is the interval containing now', () => {
            const now = dayjs.tz('2026-06-29 09:15:00', tz)
            expect(lastBucketIsInProgress(keys, tz, 'day', now)).toBe(true)
        })

        it('leaves the tail solid when the window ends in the past', () => {
            const now = dayjs.tz('2026-07-05 09:15:00', tz)
            expect(lastBucketIsInProgress(keys, tz, 'day', now)).toBe(false)
        })

        it('does not dash when there is no segment to dash', () => {
            const now = dayjs.tz('2026-06-29 09:15:00', tz)
            expect(lastBucketIsInProgress(['2026-06-29 00:00:00'], tz, 'day', now)).toBe(false)
            expect(lastBucketIsInProgress([], tz, 'day', now)).toBe(false)
        })
    })

    describe('normalizeBucket', () => {
        // The query API serializes dateTrunc buckets as ISO datetimes; they must come back in the
        // same format buildBucketKeys emits, otherwise the zero-fill join misses every bucket.
        it.each([
            ['2026-06-19T00:00:00Z', 'UTC', '2026-06-19 00:00:00'],
            ['2026-06-19T00:00:00+00:00', 'UTC', '2026-06-19 00:00:00'],
            ['2026-06-19T11:30:00Z', 'UTC', '2026-06-19 11:30:00'],
        ])('normalizes %s (%s) to %s', (raw, timezone, expected) => {
            expect(normalizeBucket(raw, timezone)).toBe(expected)
        })

        it('returns empty string for missing values', () => {
            expect(normalizeBucket(null, 'UTC')).toBe('')
            expect(normalizeBucket('', 'UTC')).toBe('')
        })

        it('produces keys that match buildBucketKeys so the activity join lands', () => {
            jest.useFakeTimers().setSystemTime(new Date('2026-06-18T12:00:00Z'))
            try {
                const bucketKeys = buildBucketKeys({ dateFrom: '-7d', dateTo: null }, 'UTC', 'day')
                const normalized = normalizeBucket('2026-06-18T00:00:00Z', 'UTC')
                expect(bucketKeys).toContain(normalized)
            } finally {
                jest.useRealTimers()
            }
        })
    })

    describe('buildKpiWindow', () => {
        it.each([
            ['2024-01-08', '2024-01-15', 'day', '2024-01-08 00:00:00', '2023-12-31'],
            ['2024-01-01', '2024-01-31', 'day', '2024-01-01 00:00:00', '2023-12-01'],
        ])(
            'extends [%s, %s] back to an equal-length prior window with cutoff at the selected start',
            (dateFrom, dateTo, interval, expectedCutoff, expectedPriorStart) => {
                const window = buildKpiWindow({ dateFrom, dateTo }, 'UTC', interval as 'day')
                expect(window.currentStartBucket).toBe(expectedCutoff)
                expect(dayjs(window.dateFrom).format('YYYY-MM-DD')).toBe(expectedPriorStart)
            }
        )

        it('rolls an hour-level range from now and steps the prior window back equally', () => {
            jest.useFakeTimers().setSystemTime(new Date('2026-06-18T12:30:00Z'))
            try {
                // "-1h" resolves to the trailing hour; prior window is the hour before that.
                const window = buildKpiWindow({ dateFrom: '-1h', dateTo: null }, 'UTC', 'minute')
                expect(window.currentStartBucket).toBe('2026-06-18 11:30:00')
                expect(dayjs(window.dateFrom).toISOString()).toBe('2026-06-18T10:29:00.000Z')
            } finally {
                jest.useRealTimers()
            }
        })

        it('resolves the relative -7d default against now', () => {
            jest.useFakeTimers().setSystemTime(new Date('2026-06-18T12:00:00Z'))
            try {
                const window = buildKpiWindow({ dateFrom: '-7d', dateTo: null }, 'UTC', 'day')
                expect(window.currentStartBucket).toBe('2026-06-11 00:00:00')
                // doubled window: prior 8 day-buckets before the cutoff
                expect(dayjs(window.dateFrom).format('YYYY-MM-DD')).toBe('2026-06-03')
            } finally {
                jest.useRealTimers()
            }
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

    describe('filter wiring', () => {
        beforeEach(() => {
            jest.clearAllMocks()
            initKeaTests()
            jest.spyOn(mockApi, 'query').mockResolvedValue({ results: [] } as any)
        })

        function reloadCallsSince(callIndex: number): any[] {
            return mockApi.query.mock.calls.slice(callIndex).map((call) => call[0] as any)
        }

        // HogQL query nodes carry filters under `.filters`; the typed
        // MCPHarnessBreakdownQuery node carries dateRange/properties/filterTestAccounts
        // at the top level. This reads whichever shape a reload used.
        const filtersOf = (call: any): Record<string, any> => call.filters ?? call

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
            const breakdowns = reloads.filter((call) => filtersOf(call).dateRange?.date_from === '-30d')
            expect(breakdowns).toHaveLength(5)
            // The KPI tile widens to an absolute doubled window so it can compare against the prior period.
            const kpi = reloads.find((call) => call.query?.includes('AS bucket'))
            expect(kpi?.filters.dateRange.date_from).not.toBe('-30d')
            expect(dayjs(kpi?.filters.dateRange.date_from).isValid()).toBe(true)
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

            const reloads = reloadCallsSince(callsBefore)
            expect(reloads.length).toBe(6)
            expect(reloads.every((call) => filtersOf(call).filterTestAccounts === enabled)).toBe(true)
        })

        it('defaults the filter from the team test_account_filters_default_checked setting', async () => {
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, test_account_filters_default_checked: true })
            jest.spyOn(mockApi, 'query').mockResolvedValue({ results: [] } as any)
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            // No explicit toggle, yet every tile filters internal users because the team default is on.
            const reloads = mockApi.query.mock.calls.map((call) => call[0] as any)
            expect(reloads.length).toBeGreaterThanOrEqual(6)
            expect(reloads.every((call) => filtersOf(call).filterTestAccounts === true)).toBe(true)
        })

        const EVENT_FILTER: AnyPropertyFilter = {
            key: '$mcp_tool_name',
            value: ['create_insight'],
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        }
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

            const reloads = reloadCallsSince(callsBefore)
            expect(reloads.length).toBe(6)
            expect(
                reloads.every((call) => JSON.stringify(filtersOf(call).properties) === JSON.stringify([filter]))
            ).toBe(true)
        })

        it('syncs property filters to the URL and clears the param when emptied', async () => {
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setPropertyFilters([EVENT_FILTER])
            }).toFinishAllListeners()
            expect(router.values.searchParams.properties).toEqual([EVENT_FILTER])

            await expectLogic(logic, () => {
                logic.actions.setPropertyFilters([])
            }).toFinishAllListeners()
            expect(router.values.searchParams.properties).toBeUndefined()
        })

        it('hydrates property filters from the URL on mount', async () => {
            router.actions.push(urls.mcpAnalyticsDashboard(), { properties: [EVENT_FILTER] })
            const logic = mcpDashboardOverviewLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.propertyFilters).toEqual([EVENT_FILTER])
        })
    })
})
