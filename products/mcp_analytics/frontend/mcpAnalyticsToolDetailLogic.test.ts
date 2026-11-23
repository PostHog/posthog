import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { DEFAULT_FACET_FILTERS, mcpAnalyticsFiltersLogic } from './mcpAnalyticsFiltersLogic'
import { type DailyToolStat, buildDailyChartData, mcpAnalyticsToolDetailLogic } from './mcpAnalyticsToolDetailLogic'
import type { ExampleCall } from './tool-quality/toolReportQueries'

jest.mock('lib/api')

function enableTeamTestAccountDefault(): void {
    teamLogic.actions.loadCurrentTeamSuccess({
        ...teamLogic.values.currentTeam!,
        test_account_filters_default_checked: true,
    })
}

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

describe('incompleteTail', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        jest.spyOn(mockApi, 'query').mockResolvedValue({ results: [] })
    })

    // An open-ended relative window always ends in the bucket that is still collecting, and a window
    // that closed in the past never does, so this holds whenever the suite runs.
    it.each([
        ['an open-ended window', '-30d', null, true],
        ['a window that already closed', '2026-06-01', '2026-06-10', false],
    ])('is %s: %s', async (_label, dateFrom, dateTo, expected) => {
        const logic = mcpAnalyticsToolDetailLogic({ toolName: 'query_run' })
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.setDateFilter(dateFrom, dateTo)
        }).toFinishAllListeners()
        // Seeded directly: with no rows the chart data short-circuits to empty, and an empty axis
        // has no tail to dash either way.
        logic.actions.loadDailyStatsSuccess([stat({ day: '2026-06-02 00:00:00', calls: 1 })])

        expect(logic.values.incompleteTail).toBe(expected)
    })
})

describe('shared filter wiring', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        jest.spyOn(mockApi, 'query').mockResolvedValue({ results: [] })
    })

    // The shared filters of each section query: top-level on MCP query nodes, under `filters` on HogQL ones.
    // The filter bar's facet queries carry none, so they are left out.
    function sectionFiltersSince(callIndex: number): Record<string, any>[] {
        return mockApi.query.mock.calls
            .slice(callIndex)
            .map((call) => call[0] as any)
            .map((query) => (query.kind === NodeKind.HogQLQuery ? query.filters : query))
            .filter((filters) => filters?.filterTestAccounts !== undefined)
    }

    const EVENT_FILTER: AnyPropertyFilter = {
        key: '$mcp_tool_name',
        value: ['query_run'],
        operator: PropertyOperator.Exact,
        type: PropertyFilterType.Event,
    }

    const EXAMPLE: ExampleCall = {
        uuid: 'call-1',
        timestamp: '2026-07-15 00:00:00',
        sessionId: 's1',
        intent: '',
        durationMs: 120,
        client: 'Claude Code',
        errorType: '',
        errorMessage: '',
        harness: 'Claude Code',
    }

    it('spreads the shared property filters into every section query and reloads on change', async () => {
        const logic = mcpAnalyticsToolDetailLogic({ toolName: 'query_run' })
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.loadAllSections()
        }).toFinishAllListeners()
        const callsBefore = mockApi.query.mock.calls.length

        await expectLogic(logic, () => {
            mcpAnalyticsFiltersLogic.actions.setPropertyFilters([EVENT_FILTER])
        }).toFinishAllListeners()

        const reloads = sectionFiltersSince(callsBefore)
        expect(reloads.length).toBe(10)
        expect(reloads.every((call) => JSON.stringify(call.properties) === JSON.stringify([EVENT_FILTER]))).toBe(true)
    })

    it.each([
        ['properties', () => mcpAnalyticsFiltersLogic.actions.setPropertyFilters([EVENT_FILTER])],
        ['test accounts', () => mcpAnalyticsFiltersLogic.actions.setFilterTestAccounts(true)],
        ['team test-account default', enableTeamTestAccountDefault],
    ])('closes the open example call on %s', async (_label, change) => {
        const logic = mcpAnalyticsToolDetailLogic({ toolName: 'query_run' })
        logic.mount()
        await expectLogic(logic, () => logic.actions.openExample(EXAMPLE)).toMatchValues({ selectedExample: EXAMPLE })

        await expectLogic(logic, change).toMatchValues({ selectedExample: null })
    })

    it.each([
        ['the test-account toggle', () => mcpAnalyticsFiltersLogic.actions.setFilterTestAccounts(true)],
        ["the team's test-account default", enableTeamTestAccountDefault],
    ])('spreads filterTestAccounts into every section query and reloads on %s', async (_label, change) => {
        const logic = mcpAnalyticsToolDetailLogic({ toolName: 'query_run' })
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.loadAllSections()
        }).toFinishAllListeners()
        const callsBefore = mockApi.query.mock.calls.length

        await expectLogic(logic, change).toFinishAllListeners()

        const reloads = sectionFiltersSince(callsBefore)
        expect(reloads.length).toBe(10)
        expect(reloads.every((call) => call.filterTestAccounts === true)).toBe(true)
    })

    it.each([
        ['no URL params', {}],
        ['shared filters', { filter_test_accounts: true, properties: [EVENT_FILTER] }],
        [
            'shared filters and a date range',
            { filter_test_accounts: true, properties: [EVENT_FILTER], date_from: '-30d' },
        ],
    ])('loads every section once when mounting with %s', async (_label, searchParams) => {
        router.actions.push(urls.mcpAnalyticsTool('query_run'), searchParams)

        const logic = mcpAnalyticsToolDetailLogic({ toolName: 'query_run' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(sectionFiltersSince(0)).toHaveLength(10)
    })

    it('reloads sections once when both shared filters hydrate from the URL', async () => {
        const logic = mcpAnalyticsToolDetailLogic({ toolName: 'query_run' })
        logic.mount()
        await expectLogic(logic, () => logic.actions.loadAllSections()).toFinishAllListeners()
        const callsBefore = mockApi.query.mock.calls.length

        await expectLogic(logic, () =>
            mcpAnalyticsFiltersLogic.actions.hydrateFilters(true, [EVENT_FILTER], DEFAULT_FACET_FILTERS)
        ).toFinishAllListeners()

        const reloads = sectionFiltersSince(callsBefore)
        expect(reloads).toHaveLength(10)
        expect(reloads.every((call) => call.filterTestAccounts === true)).toBe(true)
        expect(reloads.every((call) => JSON.stringify(call.properties) === JSON.stringify([EVENT_FILTER]))).toBe(true)
    })

    it('discards a superseded summary response so a slow earlier request cannot overwrite it', async () => {
        const logic = mcpAnalyticsToolDetailLogic({ toolName: 'query_run' })
        logic.mount()

        let resolveSlow: (value: unknown) => void = () => {}
        const slow = new Promise((resolve) => {
            resolveSlow = resolve
        })
        jest.spyOn(mockApi, 'query')
            .mockImplementationOnce(() => slow as any)
            .mockImplementationOnce(() => Promise.resolve({ results: [{ calls: 42 }] }))

        await expectLogic(logic, () => {
            logic.actions.loadSummary()
            logic.actions.loadSummary()
        }).toDispatchActions(['loadSummarySuccess'])

        expect(logic.values.summary?.calls).toBe(42)

        resolveSlow({ results: [{ calls: 1 }] })
        await new Promise((resolve) => setTimeout(resolve, 0))
        expect(logic.values.summary?.calls).toBe(42)
    })
})
