import { expectLogic } from 'kea-test-utils'

import { dataThemeLogic } from 'lib/logic/dataThemeLogic'
import { BREAKDOWN_OTHER_DISPLAY, BREAKDOWN_OTHER_STRING_LABEL } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode, NodeKind, RetentionQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightModel, RetentionPeriod } from '~/types'

import { retentionGraphLogic } from './retentionGraphLogic'
import { retentionLogic } from './retentionLogic'

const insightProps: InsightLogicProps = {
    dashboardItemId: undefined,
}

const cohortRow = (date: string, breakdownValue?: string | number | null): Record<string, any> => ({
    date,
    label: 'Day 0',
    values: [{ count: 100 }, { count: 50 }],
    ...(breakdownValue === undefined ? {} : { breakdown_value: breakdownValue }),
})

const breakdownQuery: RetentionQuery = {
    kind: NodeKind.RetentionQuery,
    retentionFilter: { period: RetentionPeriod.Day },
    breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
}

const breakdownRows = [
    cohortRow('2024-01-01T00:00:00Z', 'Chrome'),
    cohortRow('2025-01-01T00:00:00Z', 'Chrome'),
    cohortRow('2024-01-01T00:00:00Z', BREAKDOWN_OTHER_STRING_LABEL),
]

// Far enough back that no interval is still in progress, so the mean covers every point.
const COMPLETE_RANGE = { date_to: '2024-01-05' }

const overallRows = [
    {
        date: '2024-01-01T00:00:00Z',
        label: 'Day 0',
        values: [
            { count: 100, aggregation_value: 100 },
            { count: 50, aggregation_value: 60 },
        ],
    },
    {
        date: '2024-01-02T00:00:00Z',
        label: 'Day 0',
        values: [
            { count: 80, aggregation_value: 80 },
            { count: 40, aggregation_value: 20 },
        ],
    },
]

let logic: ReturnType<typeof retentionGraphLogic.build>
let builtRetentionLogic: ReturnType<typeof retentionLogic.build>

describe('retentionGraphLogic', () => {
    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/cohorts/': { count: 0, results: [] },
                '/api/environments/:team_id/data_color_themes/': [],
            },
        })
        initKeaTests(false)
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()

        dataThemeLogic.mount()
        dataThemeLogic.actions.setThemes([
            { id: 1, name: 'Test theme', colors: ['#111111', '#222222', '#333333'], is_global: true },
        ])

        dataNodeLogic({ key: 'InsightViz.new', query: {} as DataNode }).mount()

        builtRetentionLogic = retentionLogic(insightProps)
        builtRetentionLogic.mount()

        logic = retentionGraphLogic(insightProps)
        logic.mount()
    })

    async function loadResults(query: RetentionQuery, result: Record<string, any>[]): Promise<void> {
        await expectLogic(logic, () => {
            builtRetentionLogic.actions.updateQuerySource(query)
            // Rebuilding with the query as props mirrors how InsightViz passes the source query
            // down; retentionLogic.results gates on it. cachedResults set the response without
            // a network round-trip.
            dataNodeLogic({
                key: 'InsightViz.new',
                query: query as DataNode,
                cachedResults: { result } as Partial<InsightModel>,
            })
        }).toFinishAllListeners()
    }

    it('mean-per-breakdown series carry the raw breakdown value alongside the display label', async () => {
        await loadResults(breakdownQuery, breakdownRows)

        expect(logic.values.shouldShowMeanPerBreakdown).toBe(true)
        expect(logic.values.filteredTrendSeries.map((s) => [s.breakdown_value, s.rawBreakdownValue])).toEqual([
            ['Chrome', 'Chrome'],
            [BREAKDOWN_OTHER_DISPLAY, BREAKDOWN_OTHER_STRING_LABEL],
        ])
    })

    it('interval view series carry the raw breakdown value alongside the display label', async () => {
        await loadResults(
            {
                ...breakdownQuery,
                retentionFilter: { period: RetentionPeriod.Day, selectedInterval: 1 },
            },
            breakdownRows
        )

        expect(logic.values.filteredTrendSeries.map((s) => [s.breakdown_value, s.rawBreakdownValue])).toEqual([
            ['Chrome', 'Chrome'],
            [BREAKDOWN_OTHER_DISPLAY, BREAKDOWN_OTHER_STRING_LABEL],
        ])
        expect(logic.values.xAxisLabels).toEqual(['2024-01-01T00:00:00.000Z', '2025-01-01T00:00:00.000Z'])
    })

    it('per-cohort series keep rawBreakdownValue unset when filtered to one breakdown value', async () => {
        await loadResults(breakdownQuery, breakdownRows)

        builtRetentionLogic.actions.setSelectedBreakdownValue('Chrome')

        const series = logic.values.filteredTrendSeries
        expect(series).toHaveLength(2)
        // One series per cohort here: matching them all to the same breakdown color config
        // would color every cohort identically, so the raw value must not leak through.
        expect(series.map((s) => s.rawBreakdownValue)).toEqual([undefined, undefined])
    })

    it('getRetentionColorToken falls back to positional tokens and wraps at the theme size', () => {
        const token = (rawBreakdownValue: string | null, seriesIndex: number): string | null =>
            builtRetentionLogic.values.getRetentionColorToken(rawBreakdownValue, seriesIndex)[1]

        expect([token(null, 0), token(null, 1), token(null, 2), token(null, 3)]).toEqual([
            'preset-1',
            'preset-2',
            'preset-3',
            'preset-1',
        ])
        // Without a mounted dashboard there is no override, so a breakdown value is still positional
        expect(token('Chrome', 1)).toBe('preset-2')
        expect(builtRetentionLogic.values.getRetentionColor('Chrome', 1)).toBe('#222222')
    })

    describe('meanLineData', () => {
        it.each([
            ['off by default', { period: RetentionPeriod.Day }, null],
            [
                'on with no breakdown or interval selected',
                { period: RetentionPeriod.Day, showMeanLine: true },
                [100, 50],
            ],
            [
                'suppressed when an interval is selected',
                { period: RetentionPeriod.Day, showMeanLine: true, selectedInterval: 1 },
                null,
            ],
        ])('%s', async (_name, retentionFilter, expected) => {
            await loadResults(
                { kind: NodeKind.RetentionQuery, dateRange: COMPLETE_RANGE, retentionFilter },
                overallRows
            )
            expect(logic.values.meanLineData).toEqual(expected)
        })

        it('is suppressed when a breakdown is active', async () => {
            await loadResults(
                { ...breakdownQuery, retentionFilter: { period: RetentionPeriod.Day, showMeanLine: true } },
                breakdownRows
            )
            expect(logic.values.meanLineData).toBeNull()
        })

        it('stops before an in-progress interval rather than plotting its partial average', async () => {
            await loadResults(
                { kind: NodeKind.RetentionQuery, retentionFilter: { period: RetentionPeriod.Day, showMeanLine: true } },
                overallRows
            )

            expect(logic.values.meanLineData).toEqual([100])
        })

        it('uses meanValues instead of meanPercentages for property-value aggregation', async () => {
            await loadResults(
                {
                    kind: NodeKind.RetentionQuery,
                    dateRange: COMPLETE_RANGE,
                    retentionFilter: {
                        period: RetentionPeriod.Day,
                        showMeanLine: true,
                        aggregationType: 'sum',
                        aggregationProperty: 'revenue',
                    },
                },
                overallRows
            )
            expect(logic.values.meanLineData).toEqual([90, 40])
        })
    })
})
