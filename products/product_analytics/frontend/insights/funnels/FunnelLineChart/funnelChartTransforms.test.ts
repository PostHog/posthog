import type { FunnelStepWithNestedBreakdown } from '~/types'

import { buildFunnelLineSeries, buildFunnelLineTimeSeriesConfig, type IndexedFunnelStep } from './funnelChartTransforms'

const RED = '#ff0000'

const makeStep = (overrides: Partial<IndexedFunnelStep> = {}): IndexedFunnelStep =>
    ({
        id: 0,
        seriesIndex: 0,
        action_id: 'pageview',
        average_conversion_time: null,
        median_conversion_time: null,
        count: 100,
        name: 'Step 1',
        order: 0,
        type: 'events',
        converted_people_url: '',
        dropped_people_url: null,
        data: [10, 20, 30, 40, 50],
        days: ['2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14'],
        labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
        ...overrides,
    }) as IndexedFunnelStep

describe('funnelChartTransforms', () => {
    describe('buildFunnelLineSeries', () => {
        it('builds a series per indexed step with days and breakdown_value carried in meta', () => {
            const steps: IndexedFunnelStep[] = [
                makeStep({ id: 0, order: 0, name: 'Step 1', breakdown_value: 'spike' }),
                makeStep({ id: 1, order: 1, name: 'Step 2', breakdown_value: 'spike' }),
            ]
            const series = buildFunnelLineSeries(steps, { getColor: () => RED })

            expect(series).toHaveLength(2)
            expect(series[0]).toMatchObject({
                key: '0',
                label: 'Step 1',
                data: [10, 20, 30, 40, 50],
                color: RED,
            })
            expect(series[0].meta).toEqual({
                days: ['2024-06-10', '2024-06-11', '2024-06-12', '2024-06-13', '2024-06-14'],
                breakdown_value: 'spike',
                order: 0,
                label: 'Step 1',
            })
        })

        it('carries compare_label into series meta when comparing to a previous period', () => {
            const steps: IndexedFunnelStep[] = [
                makeStep({ id: 0, order: 0, breakdown_value: 'Spike', compare_label: 'current' }),
                makeStep({ id: 1, order: 1, breakdown_value: 'Spike', compare_label: 'previous' }),
            ]
            const series = buildFunnelLineSeries(steps, { getColor: () => RED })

            expect(series[0].meta).toMatchObject({ breakdown_value: 'Spike', compare_label: 'current' })
            expect(series[1].meta).toMatchObject({ breakdown_value: 'Spike', compare_label: 'previous' })
        })

        it('normalises missing data to an empty array so the trends transform accepts it', () => {
            const step = makeStep({ data: undefined as unknown as number[] })
            const [series] = buildFunnelLineSeries([step], { getColor: () => RED })

            expect(series.data).toEqual([])
        })

        it('sets a dashed in-progress tail when incompletenessOffsetFromEnd is negative', () => {
            const step = makeStep({ data: [1, 2, 3, 4, 5, 6, 7] })
            const [series] = buildFunnelLineSeries([step], {
                getColor: () => RED,
                incompletenessOffsetFromEnd: -2,
            })

            expect(series.stroke).toEqual({ partial: { fromIndex: 5 } })
        })

        it('passes the original IndexedFunnelStep to getColor (not the normalized shape)', () => {
            const step = makeStep({ breakdown_value: 'spike' })
            const getColor = jest.fn(() => RED)
            buildFunnelLineSeries([step], { getColor })

            expect(getColor).toHaveBeenCalledWith(step, 0)
        })
    })

    describe('compare against previous period', () => {
        const compareSteps: IndexedFunnelStep[] = [
            makeStep({ id: 0, seriesIndex: 0, colorIndex: 0, compare: true, compare_label: 'current' }),
            makeStep({ id: 1, seriesIndex: 1, colorIndex: 0, compare: true, compare_label: 'previous' }),
        ]

        it('builds a comparisonOf map keyed on the previous-period series so it gets dimmed', () => {
            const config = buildFunnelLineTimeSeriesConfig({
                indexedSteps: compareSteps,
                interval: 'day',
                timezone: 'UTC',
                allDays: ['2024-06-10'],
                showTrendLines: false,
            })

            expect(config.comparisonOf).toEqual({ '1': '1' })
        })

        it('omits comparisonOf when no series is a previous-period comparison', () => {
            const config = buildFunnelLineTimeSeriesConfig({
                indexedSteps: [makeStep()],
                interval: 'day',
                timezone: 'UTC',
                allDays: ['2024-06-10'],
                showTrendLines: false,
            })

            expect(config.comparisonOf).toBeUndefined()
        })
    })

    describe('buildFunnelLineTimeSeriesConfig', () => {
        it('produces a percentage y-axis tick formatter', () => {
            const config = buildFunnelLineTimeSeriesConfig({
                indexedSteps: [makeStep()],
                interval: 'day',
                timezone: 'UTC',
                allDays: ['2024-06-10'],
                showTrendLines: false,
            })

            expect(config.yAxis).toMatchObject({ format: 'percentage' })
        })

        it('passes through goal lines, trend lines, and value labels', () => {
            const config = buildFunnelLineTimeSeriesConfig({
                indexedSteps: [makeStep()],
                interval: 'day',
                timezone: 'UTC',
                allDays: ['2024-06-10'],
                showTrendLines: true,
                goalLines: [{ label: 'Goal', value: 75, displayIfCrossed: true }],
                valueLabels: { formatter: (v) => `${v}%` },
            })

            expect(config.trendLines).not.toBeUndefined()
            expect(config.trendLines).not.toHaveLength(0)
            expect(config.goalLines).toHaveLength(1)
            expect(config.valueLabels).toBeTruthy()
        })

        it('omits confidence intervals and moving average (funnels do not surface either)', () => {
            const config = buildFunnelLineTimeSeriesConfig({
                indexedSteps: [makeStep()],
                interval: 'day',
                timezone: 'UTC',
                allDays: ['2024-06-10'],
                showTrendLines: false,
            })

            expect(config.confidenceIntervals).toBeUndefined()
            expect(config.movingAverage).toBeUndefined()
        })

        it('omits the trendLines field when showTrendLines is false', () => {
            const config = buildFunnelLineTimeSeriesConfig({
                indexedSteps: [makeStep()],
                interval: 'day',
                timezone: 'UTC',
                allDays: ['2024-06-10'],
                showTrendLines: false,
            })

            expect(config.trendLines).toBeUndefined()
        })
    })

    describe('type contracts', () => {
        it('IndexedFunnelStep is assignable from FunnelStepWithNestedBreakdown', () => {
            const step: FunnelStepWithNestedBreakdown = makeStep()
            const indexed: IndexedFunnelStep = { ...step, id: 0, seriesIndex: 0, colorIndex: 0 }
            expect(indexed.id).toBe(0)
        })
    })
})
